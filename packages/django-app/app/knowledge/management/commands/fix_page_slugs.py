from typing import List, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from knowledge.commands.update_page_references_command import (
    UpdatePageReferencesCommand,
)
from knowledge.forms.update_page_references_form import UpdatePageReferencesForm
from knowledge.models import Page

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Audit (or fix) pages whose slug doesn't match slugify(title). "
        "Default is audit-only. Pass --fix to rewrite the slug and cascade "
        "reference updates to #hashtag and [[wiki-link]] mentions in blocks."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--user",
            type=str,
            help="Email of a single user to audit/fix. Default: all users.",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Apply the rename. Without this flag the command only reports.",
        )

    def handle(self, *args, **options) -> None:
        email: Optional[str] = options.get("user")
        fix: bool = options.get("fix", False)

        users = self._resolve_users(email)
        mismatches = self._collect_mismatches(users)

        if not mismatches:
            self.stdout.write(self.style.SUCCESS("No slug/title mismatches found."))
            return

        self.stdout.write(f"Found {len(mismatches)} page(s) with drift:")
        for page, expected_slug, collision in mismatches:
            tag = " [COLLISION]" if collision else ""
            self.stdout.write(
                f"  - {page.user.email} :: {page.title!r} "
                f"{page.slug!r} -> {expected_slug!r}{tag}"
            )

        if not fix:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry-run only — re-run with --fix to apply. "
                    "Pages marked [COLLISION] will be skipped."
                )
            )
            return

        fixed = 0
        skipped = 0
        for page, expected_slug, collision in mismatches:
            if collision:
                skipped += 1
                continue
            with transaction.atomic():
                old_slug = page.slug
                page.slug = expected_slug
                page.save(update_fields=["slug"])
                self._cascade_references(page, old_slug)
            fixed += 1
            self.stdout.write(
                f"  fixed: {page.user.email} :: {page.title!r} "
                f"{old_slug!r} -> {page.slug!r}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Fixed {fixed} page(s); skipped {skipped} due to collisions."
            )
        )

    def _resolve_users(self, email: Optional[str]) -> List[User]:
        if email:
            try:
                return [User.objects.get(email=email)]
            except User.DoesNotExist as exc:
                raise CommandError(f"No user with email {email!r}") from exc
        return list(User.objects.all())

    def _collect_mismatches(self, users: List[User]):
        """Return [(page, expected_slug, is_collision)] for every drifted page."""
        results = []
        for user in users:
            user_pages = list(Page.objects.filter(user=user))
            # Pre-index existing slugs for per-user collision checks. A
            # collision means another page already owns the slug we'd rename
            # to — renaming would violate the unique (user, slug) constraint.
            existing_slugs = {p.slug: p for p in user_pages}
            for page in user_pages:
                expected = slugify(page.title)
                if not expected or expected == page.slug:
                    continue
                other = existing_slugs.get(expected)
                collision = other is not None and other.uuid != page.uuid
                results.append((page, expected, collision))
        return results

    def _cascade_references(self, page: Page, old_slug: str) -> None:
        """Rewrite #old-slug hashtags in the user's blocks to point at page.slug."""
        form = UpdatePageReferencesForm(
            data={
                "page": str(page.uuid),
                "user": page.user.id,
                "old_slug": old_slug,
            }
        )
        if not form.is_valid():
            raise CommandError(
                f"Reference update form invalid for {page.title!r}: {form.errors}"
            )
        UpdatePageReferencesCommand(form).execute()
