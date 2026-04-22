from unittest.mock import Mock, patch

from django.test import TestCase

from ai_chat.commands.resume_approval_command import ResumeApprovalCommand
from ai_chat.commands.stream_send_message_command import StreamSendMessageCommand
from ai_chat.forms import ResumeApprovalForm, SendMessageForm
from ai_chat.models import AIModel, PendingToolApproval
from ai_chat.services.base_ai_service import AIUsage, PendingApproval
from ai_chat.test.helpers import (
    OpenAIProviderFactory,
    UserProviderConfigFactory,
)
from core.test.helpers import UserFactory


class ApprovalPausePersistTestCase(TestCase):
    """When the service emits pending_approval, the command persists it."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="approve@example.com")
        cls.provider = OpenAIProviderFactory()

    def setUp(self):
        self.model = AIModel.objects.create(
            name="gpt-4", provider=self.provider, display_name="GPT-4", is_active=True
        )
        UserProviderConfigFactory(
            user=self.user,
            provider=self.provider,
            api_key="approve-key",
            enabled_models=[self.model],
        )

    def _form(self):
        return SendMessageForm(
            {
                "user": self.user.id,
                "message": "Edit the page please",
                "model": "gpt-4",
                "context_blocks": [],
                "enable_notes_tools": True,
                "enable_notes_write_tools": True,
            }
        )

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.repositories.chat_message_repository.ChatMessageRepository.get_messages"
    )
    def test_pause_creates_pending_approval_and_no_assistant_message(
        self, mock_get_messages, mock_create_service
    ):
        mock_get_messages.return_value = [Mock(role="user", content="please edit")]
        pending = PendingApproval(
            messages=[{"role": "user", "content": "please edit"}],
            assistant_blocks=[
                {"type": "text", "text": "I'll edit block X."},
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "edit_block",
                    "input": {"block_uuid": "b1", "content": "new"},
                },
            ],
            tool_uses=[
                {
                    "tool_use_id": "tu_1",
                    "name": "edit_block",
                    "input": {"block_uuid": "b1", "content": "new"},
                    "requires_approval": True,
                }
            ],
        )

        def fake_stream(messages, tools, system=None, tool_executor=None):
            yield {"type": "text", "delta": "I'll edit block X."}
            yield {"type": "approval_required", "tool_uses": pending.tool_uses}
            yield {
                "type": "done",
                "content": "I'll edit block X.",
                "thinking": None,
                "usage": AIUsage(input_tokens=10, output_tokens=5),
                "tool_events": [],
                "pending_approval": pending,
            }

        mock_service = Mock()
        mock_service.stream_message.side_effect = fake_stream
        mock_create_service.return_value = mock_service

        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)
        command = StreamSendMessageCommand(form)
        events = list(command.execute())

        types = [e["type"] for e in events]
        self.assertEqual(types[-1], "approval_required")
        last = events[-1]
        self.assertTrue(last["approval_id"])
        self.assertEqual(last["tool_uses"][0]["name"], "edit_block")

        # Pending approval was persisted.
        approval = PendingToolApproval.objects.get(uuid=last["approval_id"])
        self.assertEqual(approval.status, PendingToolApproval.STATUS_PENDING)
        self.assertEqual(approval.provider_name, "openai")
        self.assertEqual(len(approval.tool_uses), 1)
        self.assertEqual(approval.assistant_blocks[1]["name"], "edit_block")

        # No assistant ChatMessage written yet — we're still paused.
        self.assertFalse(approval.session.messages.filter(role="assistant").exists())


class ResumeApprovalCommandTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="resume@example.com")
        cls.provider = OpenAIProviderFactory()

    def setUp(self):
        self.model = AIModel.objects.create(
            name="gpt-4", provider=self.provider, display_name="GPT-4", is_active=True
        )
        UserProviderConfigFactory(
            user=self.user,
            provider=self.provider,
            api_key="resume-key",
            enabled_models=[self.model],
        )

    def _create_pending(self, requires_approval: bool = True):
        from ai_chat.models import ChatSession

        session = ChatSession.objects.create(user=self.user, title="")
        approval = PendingToolApproval.objects.create(
            session=session,
            ai_model=self.model,
            provider_name="openai",
            system_prompt="",
            messages_snapshot=[{"role": "user", "content": "please edit"}],
            assistant_blocks=[
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "edit_block",
                    "input": {"block_uuid": "b1", "content": "new"},
                }
            ],
            tool_uses=[
                {
                    "tool_use_id": "tu_1",
                    "name": "edit_block",
                    "input": {"block_uuid": "b1", "content": "new"},
                    "requires_approval": requires_approval,
                }
            ],
            enable_notes_tools=True,
            enable_notes_write_tools=True,
            enable_web_search=False,
        )
        return session, approval

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch(
        "ai_chat.tools.notes_tool_executor.NotesToolExecutor.execute",
        return_value={"updated": True},
    )
    def test_resume_approved_executes_tool_and_finalizes(
        self, mock_execute, mock_create_service
    ):
        session, approval = self._create_pending()

        def fake_stream(messages, tools, system=None, tool_executor=None):
            yield {"type": "text", "delta": "Done."}
            yield {
                "type": "done",
                "content": "Done.",
                "thinking": None,
                "usage": AIUsage(input_tokens=1, output_tokens=1),
                "tool_events": [],
                "pending_approval": None,
            }

        mock_service = Mock()
        mock_service.stream_message.side_effect = fake_stream
        mock_create_service.return_value = mock_service

        form = ResumeApprovalForm(
            {
                "user": self.user.id,
                "approval_id": str(approval.uuid),
                "decisions": {"tu_1": "approve"},
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        events = list(ResumeApprovalCommand(form).execute())

        types = [e["type"] for e in events]
        self.assertEqual(types[-1], "done")
        mock_execute.assert_called_once_with("edit_block", {"block_uuid": "b1", "content": "new"})

        approval.refresh_from_db()
        self.assertEqual(approval.status, PendingToolApproval.STATUS_COMPLETED)

        # Assistant message persisted.
        assistants = session.messages.filter(role="assistant")
        self.assertEqual(assistants.count(), 1)
        self.assertIn("Done.", assistants.first().content)

    @patch("ai_chat.services.ai_service_factory.AIServiceFactory.create_service")
    @patch("ai_chat.tools.notes_tool_executor.NotesToolExecutor.execute")
    def test_resume_rejected_skips_execute(self, mock_execute, mock_create_service):
        session, approval = self._create_pending()

        def fake_stream(messages, tools, system=None, tool_executor=None):
            yield {
                "type": "done",
                "content": "",
                "thinking": None,
                "usage": AIUsage(),
                "tool_events": [],
                "pending_approval": None,
            }

        mock_service = Mock()
        mock_service.stream_message.side_effect = fake_stream
        mock_create_service.return_value = mock_service

        form = ResumeApprovalForm(
            {
                "user": self.user.id,
                "approval_id": str(approval.uuid),
                "decisions": {"tu_1": "reject"},
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        list(ResumeApprovalCommand(form).execute())

        mock_execute.assert_not_called()

        # Verify the tool_result sent back to the service noted the rejection.
        call_args = mock_service.stream_message.call_args
        resumed_messages = call_args[0][0]
        last_msg = resumed_messages[-1]
        self.assertEqual(last_msg["role"], "user")
        result_block = last_msg["content"][0]
        self.assertEqual(result_block["type"], "tool_result")
        import json

        self.assertTrue(json.loads(result_block["content"]).get("declined"))


class ResumeApprovalFormValidationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="rform@example.com")
        cls.other_user = UserFactory(email="rform-other@example.com")

    def _create_approval(self, user):
        from ai_chat.models import ChatSession

        session = ChatSession.objects.create(user=user, title="")
        return PendingToolApproval.objects.create(
            session=session,
            provider_name="anthropic",
            tool_uses=[
                {
                    "tool_use_id": "tu_1",
                    "name": "edit_block",
                    "input": {},
                    "requires_approval": True,
                }
            ],
        )

    def test_missing_decision_is_rejected(self):
        approval = self._create_approval(self.user)
        form = ResumeApprovalForm(
            {
                "user": self.user.id,
                "approval_id": str(approval.uuid),
                "decisions": {},
            }
        )
        self.assertFalse(form.is_valid())

    def test_other_users_approval_is_rejected(self):
        approval = self._create_approval(self.user)
        form = ResumeApprovalForm(
            {
                "user": self.other_user.id,
                "approval_id": str(approval.uuid),
                "decisions": {"tu_1": "approve"},
            }
        )
        self.assertFalse(form.is_valid())

    def test_invalid_decision_value_is_rejected(self):
        approval = self._create_approval(self.user)
        form = ResumeApprovalForm(
            {
                "user": self.user.id,
                "approval_id": str(approval.uuid),
                "decisions": {"tu_1": "maybe"},
            }
        )
        self.assertFalse(form.is_valid())
