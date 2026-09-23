from django.test import TestCase
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from knowledge.models import CustomVariable
from knowledge.test.helpers import CustomVariableFactory, UserFactory


class TestCustomVariablesAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def setUp(self):
        self.client = APIClient()
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_crud_round_trip(self):
        created = self.client.post(
            "/knowledge/api/custom-variables/create/",
            {"name": "food", "expansion": "{{current_time}} #food-log"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        uuid = created.data["data"]["uuid"]

        updated = self.client.put(
            "/knowledge/api/custom-variables/update/",
            {"variable_uuid": uuid, "expansion": "#food-log"},
            format="json",
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data["data"]["expansion"], "#food-log")

        listed = self.client.get("/knowledge/api/custom-variables/")
        self.assertEqual(
            [v["name"] for v in listed.data["data"]["variables"]], ["food"]
        )

        deleted = self.client.delete(
            "/knowledge/api/custom-variables/delete/",
            {"variable_uuid": uuid},
            format="json",
        )
        self.assertEqual(deleted.status_code, status.HTTP_200_OK)
        self.assertFalse(CustomVariable.objects.exists())

    def test_builtin_name_rejected_with_message(self):
        response = self.client.post(
            "/knowledge/api/custom-variables/create/",
            {"name": "today", "expansion": "x"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("built-in", response.data["errors"]["non_field_errors"][0])

    def test_list_excludes_other_users(self):
        CustomVariableFactory(user=UserFactory(), name="theirs")
        response = self.client.get("/knowledge/api/custom-variables/")
        self.assertEqual(response.data["data"]["variables"], [])
