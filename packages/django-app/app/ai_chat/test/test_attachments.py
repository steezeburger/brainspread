"""Tests for asset attachments on chat messages (issue #41 / #86 vision).

Covers:
  - SendMessageForm: validates asset_uuids ownership, image-only,
    cap, and the empty-message-with-image case.
  - SendMessageCommand._build_messages_with_images: walks history,
    pulls bytes for image attachments.
  - Provider services: each emits the right multimodal wire format
    when an `images` sidecar is present on a message.
"""

import base64
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase

from ai_chat.commands.send_message_command import SendMessageCommand
from ai_chat.forms import SendMessageForm
from ai_chat.models import AIModel, ChatMessage, ChatSession
from ai_chat.services.anthropic_service import AnthropicService
from ai_chat.services.google_service import GoogleService
from ai_chat.services.openai_service import OpenAIService
from ai_chat.test.helpers import (
    OpenAIProviderFactory,
    UserAISettingsFactory,
    UserProviderConfigFactory,
)
from assets.models import Asset
from core.test.helpers import UserFactory


def _create_image_asset(*, user, content: bytes = b"\x89PNG\r\n\x1a\n") -> Asset:
    asset = Asset.objects.create(
        user=user,
        asset_type=Asset.ASSET_TYPE_CHAT_ATTACHMENT,
        file_type=Asset.FILE_TYPE_IMAGE,
        mime_type="image/png",
        byte_size=len(content),
    )
    asset.file.save("img.png", ContentFile(content), save=True)
    return asset


class SendMessageFormAttachmentsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory(email="vision@example.com")
        cls.other_user = UserFactory(email="other@example.com")
        cls.openai_provider = OpenAIProviderFactory()
        cls.gpt4 = AIModel.objects.create(
            name="gpt-4o",
            provider=cls.openai_provider,
            display_name="GPT-4o",
            is_active=True,
        )
        UserAISettingsFactory(user=cls.user, preferred_model=cls.gpt4)
        UserProviderConfigFactory(
            user=cls.user,
            provider=cls.openai_provider,
            api_key="sk-test",
            enabled_models=[cls.gpt4],
        )

    def _form_data(self, **overrides):
        base = {
            "user": self.user.id,
            "message": "describe the image",
            "model": "gpt-4o",
        }
        base.update(overrides)
        return base

    def test_accepts_users_own_image_asset(self):
        asset = _create_image_asset(user=self.user)
        form = SendMessageForm(self._form_data(asset_uuids=[str(asset.uuid)]))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["asset_uuids"], [asset])

    def test_rejects_asset_owned_by_other_user(self):
        asset = _create_image_asset(user=self.other_user)
        form = SendMessageForm(self._form_data(asset_uuids=[str(asset.uuid)]))
        self.assertFalse(form.is_valid())
        self.assertIn("asset_uuids", form.errors)

    def test_rejects_non_image_asset(self):
        # PDFs may eventually be supported (Anthropic native) but not in
        # this slice - the form filters them out at the boundary.
        asset = Asset.objects.create(
            user=self.user,
            asset_type=Asset.ASSET_TYPE_UPLOAD,
            file_type=Asset.FILE_TYPE_PDF,
            mime_type="application/pdf",
        )
        form = SendMessageForm(self._form_data(asset_uuids=[str(asset.uuid)]))
        self.assertFalse(form.is_valid())
        self.assertIn("asset_uuids", form.errors)

    def test_rejects_too_many_attachments(self):
        assets = [_create_image_asset(user=self.user) for _ in range(6)]
        form = SendMessageForm(
            self._form_data(asset_uuids=[str(a.uuid) for a in assets])
        )
        self.assertFalse(form.is_valid())
        self.assertIn("asset_uuids", form.errors)

    def test_empty_message_allowed_when_image_attached(self):
        # Pasted screenshot with no caption is a perfectly valid request.
        asset = _create_image_asset(user=self.user)
        form = SendMessageForm(
            self._form_data(message="", asset_uuids=[str(asset.uuid)])
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_empty_message_with_no_attachment_is_rejected(self):
        form = SendMessageForm(self._form_data(message=""))
        self.assertFalse(form.is_valid())
        self.assertIn("message", form.errors)


class BuildMessagesWithImagesTestCase(TestCase):
    """Walks a real session and confirms images come back as bytes."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def test_attaches_image_bytes_for_persisted_attachment(self):
        session = ChatSession.objects.create(user=self.user)
        asset = _create_image_asset(user=self.user, content=b"PNGBYTES")

        ChatMessage.objects.create(
            session=session,
            role="user",
            content="caption",
            attachments=[
                {
                    "asset_uuid": str(asset.uuid),
                    "mime_type": asset.mime_type,
                    "file_type": asset.file_type,
                    "byte_size": asset.byte_size,
                    "original_filename": asset.original_filename,
                }
            ],
        )

        out = SendMessageCommand._build_messages_with_images(session)
        self.assertEqual(len(out), 1)
        entry = out[0]
        self.assertEqual(entry["role"], "user")
        self.assertEqual(entry["content"], "caption")
        self.assertEqual(len(entry["images"]), 1)
        self.assertEqual(entry["images"][0]["mime_type"], "image/png")
        self.assertEqual(entry["images"][0]["data"], b"PNGBYTES")

    def test_skips_messages_without_attachments(self):
        session = ChatSession.objects.create(user=self.user)
        ChatMessage.objects.create(session=session, role="user", content="just text")

        out = SendMessageCommand._build_messages_with_images(session)
        self.assertEqual(len(out), 1)
        self.assertNotIn("images", out[0])

    def test_drops_attachments_whose_bytes_are_missing(self):
        session = ChatSession.objects.create(user=self.user)
        ChatMessage.objects.create(
            session=session,
            role="user",
            content="caption",
            attachments=[
                {
                    "asset_uuid": "00000000-0000-0000-0000-000000000000",
                    "mime_type": "image/png",
                    "file_type": Asset.FILE_TYPE_IMAGE,
                    "byte_size": 0,
                    "original_filename": "missing.png",
                }
            ],
        )

        out = SendMessageCommand._build_messages_with_images(session)
        # Message survives, images key absent (the asset wasn't found).
        self.assertEqual(len(out), 1)
        self.assertNotIn("images", out[0])


class AnthropicMultimodalKwargsTestCase(TestCase):
    """Anthropic must produce image blocks BEFORE the text in content."""

    def test_image_block_emitted_with_base64_source(self):
        with patch.object(AnthropicService, "__init__", return_value=None):
            svc = AnthropicService.__new__(AnthropicService)
            svc.api_key = "sk-test"
            svc.model = "claude-sonnet-4-6"

            messages = [
                {
                    "role": "user",
                    "content": "what is this?",
                    "images": [{"mime_type": "image/png", "data": b"PNGBYTES"}],
                }
            ]
            kwargs = svc._build_kwargs(messages, tools=None, system="be concise")
            anthropic_messages = kwargs["messages"]
            self.assertEqual(len(anthropic_messages), 1)
            content = anthropic_messages[0]["content"]
            # Image block first, text second.
            self.assertEqual(content[0]["type"], "image")
            self.assertEqual(content[0]["source"]["type"], "base64")
            self.assertEqual(content[0]["source"]["media_type"], "image/png")
            self.assertEqual(
                content[0]["source"]["data"],
                base64.b64encode(b"PNGBYTES").decode("ascii"),
            )
            self.assertEqual(content[1], {"type": "text", "text": "what is this?"})


class OpenAIMultimodalKwargsTestCase(TestCase):
    def test_image_url_data_uri_emitted(self):
        messages = [
            {
                "role": "user",
                "content": "describe",
                "images": [{"mime_type": "image/jpeg", "data": b"JPEGBYTES"}],
            }
        ]
        out = OpenAIService._to_openai_messages(messages)
        self.assertEqual(len(out), 1)
        parts = out[0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "describe"})
        b64 = base64.b64encode(b"JPEGBYTES").decode("ascii")
        self.assertEqual(
            parts[1],
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            },
        )

    def test_text_only_messages_pass_through_unchanged(self):
        out = OpenAIService._to_openai_messages([{"role": "user", "content": "hi"}])
        self.assertEqual(out, [{"role": "user", "content": "hi"}])


class GoogleMultimodalPayloadTestCase(TestCase):
    """Google's payload becomes a list of parts whenever any message has an image."""

    def test_text_only_returns_string_transcript(self):
        with patch.object(GoogleService, "__init__", return_value=None):
            svc = GoogleService.__new__(GoogleService)
            svc.api_key = "k"
            svc.model = "gemini-1.5-flash"

            payload = svc._build_google_payload([{"role": "user", "content": "hello"}])
            self.assertIsInstance(payload, str)
            self.assertIn("hello", payload)

    def test_with_image_returns_list_of_parts(self):
        with patch.object(GoogleService, "__init__", return_value=None):
            svc = GoogleService.__new__(GoogleService)
            svc.api_key = "k"
            svc.model = "gemini-1.5-flash"

            payload = svc._build_google_payload(
                [
                    {
                        "role": "user",
                        "content": "what is this",
                        "images": [{"mime_type": "image/png", "data": b"PNGBYTES"}],
                    }
                ]
            )
            self.assertIsInstance(payload, list)
            # First part is the transcript, then the image part.
            self.assertIsInstance(payload[0], str)
            self.assertEqual(
                payload[1], {"mime_type": "image/png", "data": b"PNGBYTES"}
            )
