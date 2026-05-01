import logging
from typing import Any, Dict, List, Optional

from ai_chat.services.ai_service_factory import AIServiceFactory, AIServiceFactoryError
from ai_chat.services.base_ai_service import AIServiceError
from ai_chat.tools.notes_tool_executor import NotesToolExecutor
from ai_chat.tools.notes_tools import anthropic_notes_tools, openai_notes_tools
from ai_chat.tools.web_search import WebSearchTools
from assets.models import Asset
from assets.repositories import AssetRepository
from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms import SendMessageForm
from ..repositories import (
    AIModelRepository,
    ChatMessageRepository,
    ChatSessionRepository,
)

logger = logging.getLogger(__name__)


# A stable system prompt gives providers that support prompt caching something
# worth caching. Keep it short but concrete.
BRAINSPREAD_SYSTEM_PROMPT = (
    "You are the assistant embedded in brainspread, a personal note-taking app"
    " where users capture thoughts as hierarchical blocks on daily pages."
    " Be concise, direct, and helpful. Format answers as markdown."
    " When the user attaches note blocks as context, prefer them over outside"
    " knowledge and cite specific items when relevant."
)


class SendMessageCommandError(Exception):
    """Custom exception for command errors"""

    pass


class SendMessageCommand(AbstractBaseCommand):
    def __init__(self, form: SendMessageForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        try:
            message = self.form.cleaned_data["message"]
            model = self.form.cleaned_data["model"]
            session = self.form.cleaned_data.get("session_id")
            context_blocks = self.form.cleaned_data.get("context_blocks", [])
            provider_name = self.form.cleaned_data["provider_name"]
            api_key = self.form.cleaned_data["api_key"]
            user = self.form.cleaned_data["user"]

            if not session:
                session = ChatSessionRepository.create_session(user)

            formatted_message = SendMessageCommand._format_message_with_context(
                message, context_blocks
            )

            attached_assets: List[Asset] = (
                self.form.cleaned_data.get("asset_uuids") or []
            )
            ChatMessageRepository.add_message(
                session,
                "user",
                formatted_message,
                attachments=SendMessageCommand._serialize_attachments(attached_assets),
            )

            messages = SendMessageCommand._build_messages_with_images(session)

            service = AIServiceFactory.create_service(
                provider_name=provider_name,
                api_key=api_key,
                model=model,
            )
            enable_notes_tools = self.form.cleaned_data.get("enable_notes_tools")
            enable_notes_write_tools = self.form.cleaned_data.get(
                "enable_notes_write_tools"
            )
            auto_approve_notes_writes = self.form.cleaned_data.get(
                "auto_approve_notes_writes"
            )
            enable_web_search = self.form.cleaned_data.get("enable_web_search", True)
            tools, tool_executor = SendMessageCommand._build_tools(
                provider_name,
                user,
                enable_notes_tools,
                enable_web_search,
                enable_notes_write_tools=enable_notes_write_tools,
                auto_approve_notes_writes=auto_approve_notes_writes,
            )

            result = service.send_message(
                messages,
                tools,
                system=BRAINSPREAD_SYSTEM_PROMPT,
                tool_executor=tool_executor,
            )

            ai_model = AIModelRepository.get_by_name(model)

            assistant_message = ChatMessageRepository.add_message(
                session,
                "assistant",
                result.content,
                ai_model=ai_model,
                thinking=result.thinking or "",
                usage=result.usage,
                tool_events=result.tool_events,
            )

            return {
                "response": result.content,
                "session_id": str(session.uuid),
                "message": self._serialize_message(assistant_message, ai_model),
            }

        except (AIServiceError, AIServiceFactoryError) as e:
            logger.error(f"AI service error for user {user.id}: {str(e)}")
            if session:
                ai_model = AIModelRepository.get_by_name(model)
                error_message = (
                    f"Sorry, I'm experiencing technical difficulties: {str(e)}"
                )
                ChatMessageRepository.add_message(
                    session,
                    "assistant",
                    error_message,
                    ai_model=ai_model,
                )
            raise SendMessageCommandError(f"AI service error: {str(e)}") from e

        except SendMessageCommandError:
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error in SendMessageCommand for user {user.id}: {str(e)}"
            )
            raise SendMessageCommandError(
                f"An unexpected error occurred: {str(e)}"
            ) from e

    @staticmethod
    def _serialize_message(message, ai_model) -> Dict[str, Any]:
        # getattr-with-default keeps this resilient to test mocks that
        # don't pre-configure attachments (which is a new field).
        attachments = getattr(message, "attachments", None)
        if not isinstance(attachments, list):
            attachments = []
        return {
            "role": message.role,
            "content": message.content,
            "thinking": message.thinking or None,
            "created_at": message.created_at.isoformat(),
            "tool_events": list(message.tool_events or []),
            "attachments": list(attachments),
            "usage": {
                "input_tokens": message.input_tokens,
                "output_tokens": message.output_tokens,
                "cache_creation_input_tokens": message.cache_creation_input_tokens,
                "cache_read_input_tokens": message.cache_read_input_tokens,
            },
            "ai_model": (
                {
                    "name": ai_model.name,
                    "display_name": ai_model.display_name,
                    "provider": ai_model.provider.name,
                }
                if ai_model
                else None
            ),
        }

    @staticmethod
    def _serialize_attachments(assets: List[Asset]) -> List[Dict[str, Any]]:
        """
        Persist-safe metadata for attached assets. The bytes themselves
        live on disk and are re-read per API call by
        _build_messages_with_images so we don't bloat the messages JSON.
        """
        return [
            {
                "asset_uuid": str(a.uuid),
                "mime_type": a.mime_type,
                "file_type": a.file_type,
                "byte_size": a.byte_size,
                "original_filename": a.original_filename,
            }
            for a in assets
        ]

    @staticmethod
    def _build_messages_with_images(session) -> List[Dict[str, Any]]:
        """
        Walk the session's persisted history and attach the bytes for any
        image attachments. Provider services consume the resulting list via
        the `images` sidecar key per message and turn that into their
        provider-specific multimodal block shape.

        Bytes are read fresh from disk every turn rather than cached on the
        ChatMessage row - keeps the row small and lets a future S3 backend
        kick in without a data migration.
        """
        out: List[Dict[str, Any]] = []
        for msg in ChatMessageRepository.get_messages(session):
            entry: Dict[str, Any] = {"role": msg.role, "content": msg.content}
            attachments = getattr(msg, "attachments", None)
            if not isinstance(attachments, list):
                attachments = []
            images: List[Dict[str, Any]] = []
            for att in attachments:
                file_type = att.get("file_type")
                if file_type != Asset.FILE_TYPE_IMAGE:
                    # Non-image attachments are persisted for the UI but
                    # not yet forwarded to providers (see form: only images
                    # are accepted today).
                    continue
                asset = AssetRepository.get_by_uuid(
                    uuid=att.get("asset_uuid", ""), user=None
                )
                if asset is None or not asset.file:
                    logger.warning(
                        "Skipping missing asset %s on message %s",
                        att.get("asset_uuid"),
                        getattr(msg, "uuid", None),
                    )
                    continue
                try:
                    with asset.file.open("rb") as fh:
                        data = fh.read()
                except FileNotFoundError:
                    logger.warning("Asset bytes missing on disk for %s", asset.uuid)
                    continue
                images.append(
                    {
                        "mime_type": asset.mime_type or "application/octet-stream",
                        "data": data,
                    }
                )
            if images:
                entry["images"] = images
            out.append(entry)
        return out

    @staticmethod
    def _format_message_with_context(message: str, context_blocks: List[Dict]) -> str:
        """
        Render context blocks as a markdown bullet list prepended to the
        user's question. Each entry includes:

          - A `[block <uuid> on page <page_uuid>]` marker so the model
            can target it with notes tools. Both ids are needed because
            create_block requires `page_uuid` AND optionally
            `parent_uuid`; without the page id the AI ends up calling
            search_notes / get_page_by_title to hunt for the page,
            which fails when the user attached the block visually
            without writing its title in the chat.
          - The text content (when present).
          - An "(image attached: <filename>)" marker when the block has
            an asset, so an image-only block isn't silently dropped from
            the text context (it still shows up in the multimodal
            payload, but the text marker tells the AI which block uuid
            that image came from).
        """
        if not context_blocks:
            return message

        context_text_parts = []
        for block in context_blocks:
            uuid = (block.get("uuid") or "").strip()
            page_uuid = (block.get("page_uuid") or "").strip()
            content = (block.get("content") or "").strip()
            block_type = block.get("block_type", "bullet")
            asset = block.get("asset") or None

            if block_type == "todo":
                prefix = "☐"
            elif block_type == "done":
                prefix = "☑"
            else:
                prefix = "•"

            bits = []
            if uuid and page_uuid:
                bits.append(f"[block {uuid} on page {page_uuid}]")
            elif uuid:
                bits.append(f"[block {uuid}]")
            if content:
                bits.append(content)
            if asset:
                label = (
                    asset.get("original_filename") or asset.get("file_type") or "asset"
                )
                if asset.get("file_type") == "image":
                    bits.append(f"(image attached: {label})")
                else:
                    bits.append(f"(file attached: {label})")

            if len(bits) == 1 and bits[0].startswith("[block "):
                # Block with no content and no asset - nothing useful to
                # surface, skip rather than emit a naked uuid line.
                continue
            if bits:
                context_text_parts.append(f"{prefix} {' '.join(bits)}")

        if not context_text_parts:
            return message

        context_section = "\n".join(context_text_parts)
        return f"""**Context from my notes:**
{context_section}

**My question:**
{message}"""

    @staticmethod
    def _get_web_search_tools(
        provider_name: str,
    ) -> Optional[List[Dict[str, Any]]]:
        """Get web search tools configuration for the specified provider."""
        if provider_name == "anthropic":
            return [WebSearchTools.anthropic_web_search()]
        elif provider_name == "openai":
            return [WebSearchTools.openai_web_search()]
        elif provider_name == "google":
            return [WebSearchTools.google_search()]

        return None

    @staticmethod
    def _build_tools(
        provider_name,
        user,
        enable_notes_tools,
        enable_web_search: bool = True,
        enable_notes_write_tools: bool = False,
        auto_approve_notes_writes: bool = False,
    ):
        """Combine provider-native web search with optional notes tools.

        Returns the tools payload plus a ToolExecutor if custom tools are
        active — only Anthropic's service runs the custom tool loop today,
        so for other providers notes tools are skipped.
        """
        tools: List[Dict[str, Any]] = []
        if enable_web_search:
            web_tools = SendMessageCommand._get_web_search_tools(provider_name)
            if web_tools:
                tools.extend(web_tools)

        tool_executor = None
        any_notes = enable_notes_tools or enable_notes_write_tools
        if any_notes:
            if provider_name == "anthropic":
                tools.extend(
                    anthropic_notes_tools(include_writes=enable_notes_write_tools)
                )
                tool_executor = NotesToolExecutor(
                    user,
                    allow_writes=enable_notes_write_tools,
                    auto_approve_writes=(
                        enable_notes_write_tools and auto_approve_notes_writes
                    ),
                )
            elif provider_name == "openai":
                # OpenAI's Responses API is only invoked when tools are present;
                # mixing function-calling with the Responses web_search path is
                # brittle, so we only surface notes tools here for Anthropic
                # until the tool loop is implemented for OpenAI.
                tools.extend(
                    openai_notes_tools(include_writes=enable_notes_write_tools)
                )

        return (tools or None), tool_executor
