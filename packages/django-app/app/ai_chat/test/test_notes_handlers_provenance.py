from django.test import TestCase

from ai_chat.tools.notes_handlers import _create_block, _create_blocks_bulk
from core.llm_tools import ToolContext
from knowledge.models import Block
from knowledge.repositories.block_repository import BlockRepository
from knowledge.test.helpers import PageFactory, UserFactory


class NotesHandlersProvenanceTests(TestCase):
    """Blocks created through the AI-chat tool handlers must carry the
    ai_chat provenance stamp (issue: know whether a block was written by
    the web UI, AI chat, or MCP)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.page = PageFactory(user=cls.user)

    def _ctx(self) -> ToolContext:
        return ToolContext(user=self.user, current_page_uuid=str(self.page.uuid))

    def test_create_block_stamps_ai_chat(self):
        result = _create_block(
            self._ctx(),
            {"content": "from the assistant", "page_uuid": str(self.page.uuid)},
        )
        self.assertTrue(result.get("created"), result)
        block = BlockRepository.get_by_uuid(result["block"]["block_uuid"])
        self.assertEqual(block.created_via, Block.CREATED_VIA_AI_CHAT)

    def test_create_blocks_bulk_stamps_ai_chat(self):
        result = _create_blocks_bulk(
            self._ctx(),
            {
                "page_uuid": str(self.page.uuid),
                "blocks": [{"content": "one"}, {"content": "two"}],
            },
        )
        self.assertEqual(result.get("created_count"), 2, result)
        for row in result["blocks"]:
            block = BlockRepository.get_by_uuid(row["block_uuid"])
            self.assertEqual(block.created_via, Block.CREATED_VIA_AI_CHAT)
