from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from knowledge.models import Reminder, ReminderAction
from knowledge.services.reminder_actions import (
    build_action_url,
    create_action_tokens,
)

from ..helpers import BlockFactory, PageFactory, UserFactory


class CreateActionTokensTests(TestCase):
    def setUp(self) -> None:
        self.user = UserFactory()
        self.page = PageFactory(user=self.user)
        self.block = BlockFactory(user=self.user, page=self.page)
        self.reminder = Reminder.objects.create(
            block=self.block,
            fire_at=timezone.now(),
        )

    def test_creates_one_token_per_default_action(self) -> None:
        rows = create_action_tokens(self.reminder)

        self.assertEqual(
            set(rows.keys()),
            {
                ReminderAction.ACTION_COMPLETE,
                ReminderAction.ACTION_SNOOZE_1H,
                ReminderAction.ACTION_SNOOZE_1D,
            },
        )
        # Tokens are unique per row — collisions would break the
        # uniqueness constraint at write time, but assert here too.
        self.assertEqual(len({r.token for r in rows.values()}), 3)

    def test_tokens_default_expiry_uses_model_ttl(self) -> None:
        pinned = timezone.now()

        rows = create_action_tokens(self.reminder, now=pinned)

        for row in rows.values():
            self.assertAlmostEqual(
                (row.expires_at - pinned).total_seconds(),
                ReminderAction.DEFAULT_TTL.total_seconds(),
                delta=2,
            )

    def test_actions_arg_subsets_what_gets_created(self) -> None:
        rows = create_action_tokens(
            self.reminder, actions=[ReminderAction.ACTION_COMPLETE]
        )
        self.assertEqual(list(rows.keys()), [ReminderAction.ACTION_COMPLETE])
        self.assertEqual(self.reminder.actions.count(), 1)

    def test_custom_ttl_is_respected(self) -> None:
        pinned = timezone.now()
        rows = create_action_tokens(self.reminder, ttl=timedelta(hours=2), now=pinned)
        for row in rows.values():
            self.assertAlmostEqual(
                (row.expires_at - pinned).total_seconds(),
                7200,
                delta=2,
            )


class BuildActionUrlTests(TestCase):
    def test_builds_absolute_url_when_site_url_is_real(self) -> None:
        url = build_action_url("https://app.example.com", "tok123")
        self.assertEqual(url, "https://app.example.com/knowledge/r/tok123/")

    def test_strips_trailing_slash_on_site_url(self) -> None:
        url = build_action_url("https://app.example.com/", "tok")
        self.assertEqual(url, "https://app.example.com/knowledge/r/tok/")

    def test_returns_empty_for_placeholder_site_url(self) -> None:
        # Default SITE_URL in dev/test is "0.0.0.0" — without a scheme,
        # the embed link would be invalid, so the helper returns "" and
        # the caller renders no action row.
        self.assertEqual(build_action_url("0.0.0.0", "tok"), "")
        self.assertEqual(build_action_url("", "tok"), "")
