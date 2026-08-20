from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.test.helpers import UserFactory
from knowledge.models import AutomationRun
from knowledge.test.helpers import BlockFactory, PageFactory


class RunAutomationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.tag_page = PageFactory(user=cls.user, title="automation", slug="automation")
        page = PageFactory(user=cls.user, title="Autos", slug="autos-view")
        cls.automation = BlockFactory(
            user=cls.user,
            page=page,
            content="View sweep #automation",
            properties={
                "trigger": "manual",
                "query": "type:todo",
                "action": "set_type done",
            },
        )
        cls.automation.pages.add(cls.tag_page)

    def setUp(self):
        self.client = APIClient()
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_runs_automation_and_returns_run_record(self):
        notes = PageFactory(user=self.user, title="Notes", slug="notes-view")
        todo = BlockFactory(
            user=self.user, page=notes, block_type="todo", content="TODO x"
        )

        response = self.client.post(
            "/knowledge/api/automations/run/",
            {"automation_block": str(self.automation.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["status"], AutomationRun.STATUS_SUCCEEDED
        )
        self.assertEqual(response.data["data"]["trigger"], AutomationRun.TRIGGER_MANUAL)
        todo.refresh_from_db()
        self.assertEqual(todo.block_type, "done")

    def test_failed_run_is_a_successful_call_with_failed_payload(self):
        broken = BlockFactory(
            user=self.user,
            page=PageFactory(user=self.user, title="B", slug="autos-view-b"),
            content="Broken #automation",
            properties={"trigger": "telepathy"},
        )
        broken.pages.add(self.tag_page)

        response = self.client.post(
            "/knowledge/api/automations/run/",
            {"automation_block": str(broken.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], AutomationRun.STATUS_FAILED)
        self.assertIn("telepathy", response.data["data"]["last_error"])

    def test_other_users_automation_is_rejected(self):
        other = UserFactory()
        other_page = PageFactory(user=other, title="O", slug="autos-view-o")
        foreign = BlockFactory(
            user=other,
            page=other_page,
            content="x #automation",
            properties={"trigger": "manual", "action": "set_type done"},
        )

        response = self.client.post(
            "/knowledge/api/automations/run/",
            {"automation_block": str(foreign.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_requires_authentication(self):
        self.client.credentials()
        response = self.client.post(
            "/knowledge/api/automations/run/",
            {"automation_block": str(self.automation.uuid)},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
