from typing import Any

from django.core.management.base import BaseCommand, CommandError

from knowledge.commands.normalize_block_order_command import (
    NormalizeBlockOrderCommand,
)
from knowledge.forms.normalize_block_order_form import NormalizeBlockOrderForm
from knowledge.repositories import PageRepository


class Command(BaseCommand):
    """CLI shell around NormalizeBlockOrderCommand — one repair
    implementation, not a parallel one. This command previously carried
    its own renumbering loop with subtly different semantics (no page
    filter on child groups, per-row saves, created_at-only sort), so a
    run of it could reshuffle pages the admin action had just repaired.
    Now both surfaces share the command's group semantics exactly."""

    help = (
        "Repair duplicate/gapped block orders: renumber every rendered "
        "sibling group on each page"
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making actual changes",
        )
        parser.add_argument(
            "--page-date",
            type=str,
            help="Fix ordering only for a specific page date (YYYY-MM-DD format)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run: bool = options["dry_run"]
        page_date = options.get("page_date")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        pages = list(PageRepository.get_pages_for_order_repair(page_date=page_date))
        self.stdout.write(f"Processing {len(pages)} page(s)...")

        total_renumbered = 0
        for page in pages:
            form = NormalizeBlockOrderForm(data={"page": page, "dry_run": dry_run})
            if not form.is_valid():
                raise CommandError(f"page {page.uuid}: {form.errors.as_text()}")
            result = NormalizeBlockOrderCommand(form).execute()
            total_renumbered += result["renumbered"]
            if result["renumbered"] > 0:
                page_display = page.date if page.date else page.title
                self.stdout.write(
                    f"  Page '{page_display}': "
                    f"{result['renumbered']} blocks reordered"
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN COMPLETE: Would fix {total_renumbered} blocks "
                    f"across {len(pages)} pages"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"COMPLETE: Fixed {total_renumbered} blocks across "
                    f"{len(pages)} pages"
                )
            )
