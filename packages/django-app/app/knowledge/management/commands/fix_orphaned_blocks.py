from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from core.models import User
from knowledge.repositories import BlockRepository


class Command(BaseCommand):
    help = (
        "Promote blocks whose parent lives on a different page back to "
        "root on their own page. Older move paths could leave blocks "
        "with a cross-page parent — visible to type-based custom views "
        "but invisible to the recursive page render."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything",
        )
        parser.add_argument(
            "--user",
            type=str,
            help="Limit to one user's blocks (email). Omit to scan all users.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        user_email: str = options.get("user")

        user = None
        if user_email:
            try:
                user = User.objects.get(email=user_email)
            except User.DoesNotExist:
                raise CommandError(f"User with email '{user_email}' does not exist")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - no changes will be made")
            )

        orphans = list(
            BlockRepository.get_orphaned_blocks(user=user).select_related(
                "page", "parent__page"
            )
        )

        if not orphans:
            self.stdout.write(self.style.SUCCESS("No orphaned blocks found."))
            return

        self.stdout.write(f"Found {len(orphans)} orphaned block(s).")

        # Compute new orders up front so we put each fixed block at the
        # bottom of its page (avoids order collisions with existing roots).
        # Reuse a cached max per page across the same run.
        next_order_for_page: dict = {}

        def next_order(page_id: int) -> int:
            if page_id not in next_order_for_page:
                current_max = (
                    BlockRepository.get_queryset()
                    .filter(page_id=page_id, parent__isnull=True)
                    .aggregate(m=Max("order"))["m"]
                )
                next_order_for_page[page_id] = (current_max or 0) + 1
            else:
                next_order_for_page[page_id] += 1
            return next_order_for_page[page_id]

        fixed = 0
        with transaction.atomic():
            for block in orphans:
                new_order = next_order(block.page_id)
                self.stdout.write(
                    f"  block={block.uuid} page={block.page.title!r} "
                    f"parent_page={block.parent.page.title!r} -> root@{new_order}"
                )
                if not dry_run:
                    block.parent = None
                    block.order = new_order
                    block.save(update_fields=["parent", "order"])
                fixed += 1

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN COMPLETE: would fix {fixed} block(s)"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"COMPLETE: fixed {fixed} block(s)")
            )
