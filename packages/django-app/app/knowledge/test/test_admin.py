from django.contrib import admin
from django.test import TestCase

from knowledge.admin import AutomationRunAdmin
from knowledge.models import AutomationRun

from .helpers import BlockFactory, UserFactory


class TestAutomationRunAdminBlockLink(TestCase):
    """automation_block_uuid is a soft reference (no FK), so the admin
    resolves it by hand to build a link — worth covering both the
    happy path and the deleted-block fallback directly."""

    def setUp(self):
        self.admin = AutomationRunAdmin(AutomationRun, admin.site)

    def test_links_to_the_block_when_it_still_exists(self):
        block = BlockFactory(user=UserFactory())
        run = AutomationRun(automation_block_uuid=str(block.uuid))

        html = self.admin.automation_block_link(run)

        self.assertIn(f"/admin/knowledge/block/{block.pk}/change/", html)
        self.assertIn(str(block.uuid), html)

    def test_falls_back_to_the_bare_uuid_when_the_block_is_gone(self):
        run = AutomationRun(
            automation_block_uuid="00000000-0000-0000-0000-000000000000"
        )

        result = self.admin.automation_block_link(run)

        self.assertEqual(result, "00000000-0000-0000-0000-000000000000")
