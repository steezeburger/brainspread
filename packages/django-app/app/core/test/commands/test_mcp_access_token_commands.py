from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.commands import (
    CreateMcpAccessTokenCommand,
    ListMcpAccessTokensCommand,
    RevokeMcpAccessTokenCommand,
)
from core.forms import (
    CreateMcpAccessTokenForm,
    ListMcpAccessTokensForm,
    RevokeMcpAccessTokenForm,
)
from core.mcp_access_keys import MCP_ACCESS_KEY_PREFIX, hash_mcp_access_key
from core.repositories import McpAccessTokenRepository
from core.test.helpers import McpAccessTokenFactory, UserFactory


class TestCreateMcpAccessTokenCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _create(self, **data):
        form = CreateMcpAccessTokenForm({"user": self.user.id, **data})
        self.assertTrue(form.is_valid(), form.errors)
        return CreateMcpAccessTokenCommand(form).execute()

    def test_should_store_only_a_hash_of_the_key(self):
        result = self._create(name="laptop")

        self.assertTrue(result.key.startswith(MCP_ACCESS_KEY_PREFIX))
        self.assertEqual(result.token.key_hash, hash_mcp_access_key(result.key))
        self.assertNotIn(result.key, result.token.key_hash)
        self.assertEqual(result.token.key_prefix, result.key[:12])
        self.assertEqual(result.token.name, "laptop")

    def test_should_not_expire_by_default(self):
        result = self._create(name="laptop")
        self.assertIsNone(result.token.expires_at)

    def test_should_set_expiry_when_given_days(self):
        result = self._create(name="laptop", expires_in_days=30)
        expected = timezone.now() + timedelta(days=30)
        self.assertAlmostEqual(
            result.token.expires_at, expected, delta=timedelta(seconds=5)
        )

    def test_should_mint_distinct_keys(self):
        first = self._create(name="a")
        second = self._create(name="b")
        self.assertNotEqual(first.key, second.key)

    def test_should_reject_blank_name(self):
        form = CreateMcpAccessTokenForm({"user": self.user.id, "name": "   "})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)


class TestListMcpAccessTokensCommand(TestCase):
    def test_should_list_only_the_users_unrevoked_tokens(self):
        user = UserFactory()
        active = McpAccessTokenFactory(user=user)
        expired = McpAccessTokenFactory(
            user=user, expires_at=timezone.now() - timedelta(days=1)
        )
        McpAccessTokenFactory(user=user, revoked_at=timezone.now())
        McpAccessTokenFactory()  # someone else's

        form = ListMcpAccessTokensForm({"user": user.id})
        self.assertTrue(form.is_valid(), form.errors)
        tokens = ListMcpAccessTokensCommand(form).execute()

        self.assertCountEqual(tokens, [active, expired])


class TestRevokeMcpAccessTokenCommand(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()

    def _revoke(self, token_uuid):
        form = RevokeMcpAccessTokenForm(
            {"user": self.user.id, "token_uuid": str(token_uuid)}
        )
        self.assertTrue(form.is_valid(), form.errors)
        return RevokeMcpAccessTokenCommand(form).execute()

    def test_should_revoke_the_token(self):
        raw_key = "bsmcp_revoke-me"
        token = McpAccessTokenFactory(user=self.user, raw_key=raw_key)

        self._revoke(token.uuid)

        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        self.assertIsNone(McpAccessTokenRepository.get_usable_by_key(raw_key))

    def test_should_not_revoke_another_users_token(self):
        other = McpAccessTokenFactory()
        with self.assertRaises(ValidationError):
            self._revoke(other.uuid)
        other.refresh_from_db()
        self.assertIsNone(other.revoked_at)

    def test_should_not_revoke_twice(self):
        token = McpAccessTokenFactory(user=self.user)
        self._revoke(token.uuid)
        with self.assertRaises(ValidationError):
            self._revoke(token.uuid)
