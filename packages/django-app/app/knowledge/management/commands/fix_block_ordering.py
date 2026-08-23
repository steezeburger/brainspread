from django.core.management.base import BaseCommand
from django.db import transaction

from knowledge.models import Block, Page


class Command(BaseCommand):
    help = (
        "Fix block ordering by assigning sequential order values to blocks with order=0"
    )

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        page_date = options.get("page_date")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        # Get pages to process
        pages_queryset = Page.objects.all()
        if page_date:
            pages_queryset = pages_queryset.filter(date=page_date)

        total_pages = pages_queryset.count()
        self.stdout.write(f"Processing {total_pages} page(s)...")

        total_blocks_fixed = 0

        for page in pages_queryset:
            blocks_fixed = self._fix_page_ordering(page, dry_run)
            total_blocks_fixed += blocks_fixed

            if blocks_fixed > 0:
                page_display = page.date if page.date else page.title
                self.stdout.write(
                    f"  Page '{page_display}': {blocks_fixed} blocks reordered"
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN COMPLETE: Would fix {total_blocks_fixed} blocks across {total_pages} pages"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"COMPLETE: Fixed {total_blocks_fixed} blocks across {total_pages} pages"
                )
            )

    def _fix_page_ordering(self, page: Page, dry_run: bool) -> int:
        """Fix ordering for a single page, returns number of blocks fixed"""
        with transaction.atomic():
            # Sort by (order, created_at, id) — the SAME semantics as
            # NormalizeBlockOrderCommand and the Page admin's "Fix block
            # ordering" action, so running one repair after the other
            # never reshuffles a page. (This command previously sorted
            # by created_at alone, which scrambled hand-dragged order.)
            root_blocks = Block.objects.filter(page=page, parent=None).order_by(
                "order", "created_at", "id"
            )

            blocks_to_fix = []
            current_order = 0

            for block in root_blocks:
                # Assign sequential order values starting from 0
                if block.order != current_order:
                    blocks_to_fix.append((block, current_order))
                current_order += 1

            # Also fix child blocks recursively
            for block in root_blocks:
                child_fixes = self._fix_children_ordering(block, dry_run)
                blocks_to_fix.extend(child_fixes)

            if not dry_run and blocks_to_fix:
                # Apply the fixes
                for block, new_order in blocks_to_fix:
                    block.order = new_order
                    block.save(update_fields=["order"])

            return len(blocks_to_fix)

    def _fix_children_ordering(self, parent_block: Block, dry_run: bool) -> list:
        """Fix ordering for children of a block recursively"""
        fixes = []
        children = Block.objects.filter(parent=parent_block).order_by(
            "order", "created_at", "id"
        )

        current_order = 0
        for child in children:
            if child.order != current_order:
                fixes.append((child, current_order))
            current_order += 1

            # Recursively fix grandchildren
            grandchild_fixes = self._fix_children_ordering(child, dry_run)
            fixes.extend(grandchild_fixes)

        return fixes
