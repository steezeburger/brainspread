from django.contrib.auth import get_user_model
from factory import Faker, LazyAttribute, LazyFunction, SubFactory
from factory.django import DjangoModelFactory

from core.mcp_access_keys import (
    MCP_ACCESS_KEY_DISPLAY_LENGTH,
    generate_mcp_access_key,
    hash_mcp_access_key,
)
from core.models import McpAccessToken

User = get_user_model()


class UserFactory(DjangoModelFactory):
    email = Faker("email")
    is_active = True

    class Meta:
        model = User


class McpAccessTokenFactory(DjangoModelFactory):
    """Pass ``raw_key=...`` to know the plaintext key in a test."""

    user = SubFactory(UserFactory)
    name = Faker("word")
    key_prefix = LazyAttribute(lambda o: o.raw_key[:MCP_ACCESS_KEY_DISPLAY_LENGTH])
    key_hash = LazyAttribute(lambda o: hash_mcp_access_key(o.raw_key))

    class Params:
        raw_key = LazyFunction(generate_mcp_access_key)

    class Meta:
        model = McpAccessToken
