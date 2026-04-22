from typing import Dict, List, Optional, Tuple

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from knowledge.commands.sync_block_tags_command import SyncBlockTagsCommand
from knowledge.forms.sync_block_tags_form import SyncBlockTagsForm
from knowledge.models import Block, Page

User = get_user_model()

# Page spec: (slug, title, block contents).
# Each block content may contain #hashtags — those become graph edges via
# SyncBlockTagsCommand, which mirrors the real UI flow.
PAGES: List[Tuple[str, str, List[str]]] = [
    # Cluster 1: software
    (
        "python",
        "Python",
        [
            "Dynamic, high-level language. See #django and #testing for common uses.",
            "Type hints pair well with #mypy",
            "Ecosystem highlights: #pytest #ruff #black",
        ],
    ),
    (
        "django",
        "Django",
        [
            "Web framework built on #python",
            "ORM patterns — prefer #repositories over fat models",
            "Testing strategies live in #testing",
        ],
    ),
    (
        "testing",
        "Testing",
        [
            "#pytest is the de-facto runner for #python",
            "Use #factoryboy for realistic fixtures",
            "Coverage goals: keep critical #django paths green",
        ],
    ),
    (
        "pytest",
        "Pytest",
        [
            "Fixtures and parametrization make #testing concise",
            "Markers let you split slow suites — see #testing",
        ],
    ),
    (
        "ruff",
        "Ruff",
        [
            "Fast #python linter written in Rust",
            "Pairs well with #black formatting",
        ],
    ),
    (
        "black",
        "Black",
        ["Opinionated #python formatter", "Keeps diffs small across #testing suites"],
    ),
    (
        "mypy",
        "Mypy",
        [
            "Static type checker for #python",
            "Complements #testing with compile-time checks",
        ],
    ),
    (
        "factoryboy",
        "FactoryBoy",
        ["Fixture factories for #testing", "Works smoothly with #django models"],
    ),
    (
        "repositories",
        "Repository Pattern",
        [
            "Keeps queries out of views and commands",
            "Used throughout this #django codebase",
        ],
    ),
    # Cluster 2: knowledge management
    (
        "logseq",
        "Logseq",
        [
            "Outliner-style #knowledge-management tool",
            "Inspired this project's block model and #graph-view",
            "Hashtags are first-class citizens, see #tagging",
        ],
    ),
    (
        "knowledge-management",
        "Knowledge Management",
        [
            "Captures notes, ideas, and references over time",
            "Tools: #logseq #obsidian #roam",
            "Graph visualization (#graph-view) surfaces hidden connections",
        ],
    ),
    (
        "obsidian",
        "Obsidian",
        [
            "Markdown-based #knowledge-management app",
            "Strong community around #tagging",
        ],
    ),
    (
        "roam",
        "Roam Research",
        ["Pioneered the bidirectional-linking approach to #knowledge-management"],
    ),
    (
        "tagging",
        "Tagging",
        [
            "Hashtag syntax keeps linking lightweight",
            "Every #tagging reference is also a graph edge, see #graph-view",
        ],
    ),
    (
        "graph-view",
        "Graph View",
        [
            "Force-directed visualization of pages and their links",
            "Nodes are pages; edges come from #tagging",
            "Inspired by #logseq and #obsidian",
        ],
    ),
    # Cluster 3: a standalone small cluster
    (
        "coffee",
        "Coffee",
        ["Morning fuel", "Pairs with #reading"],
    ),
    (
        "reading",
        "Reading",
        ["Best with #coffee", "Recent focus: #knowledge-management essays"],
    ),
    # Orphans (no links in, no links out) — useful for testing the
    # "hide orphans" toggle in the graph view.
    ("orphan-one", "Orphan One", ["Standalone note with no references"]),
    ("orphan-two", "Orphan Two", ["Another note that intentionally links nowhere"]),
]


class Command(BaseCommand):
    help = (
        "Seed a user with a linked set of pages designed to exercise the "
        "graph view. Pages reference each other via #hashtags, which get "
        "synced to the Block.pages M2M the same way the UI does."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--user",
            type=str,
            help="Email of the user to seed. Defaults to the first superuser.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Delete previously-seeded demo pages for the user before "
                "recreating them. Demo pages are identified by their known "
                "slugs."
            ),
        )

    def handle(self, *args, **options) -> None:
        user = self._resolve_user(options.get("user"))
        reset: bool = options.get("reset", False)

        with transaction.atomic():
            if reset:
                self._delete_demo_pages(user)

            pages, skipped_pages = self._create_pages(user)
            created_blocks = self._create_blocks(user, pages)

        new_pages = len(pages) - skipped_pages
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded graph demo for {user.email}: "
                f"{new_pages} new pages, "
                f"{skipped_pages} already existed, "
                f"{created_blocks} blocks created."
            )
        )

    def _resolve_user(self, email: Optional[str]) -> User:
        if email:
            try:
                return User.objects.get(email=email)
            except User.DoesNotExist as exc:
                raise CommandError(f"No user with email {email!r}") from exc
        user = User.objects.filter(is_superuser=True).order_by("id").first()
        if not user:
            raise CommandError(
                "No --user given and no superuser found. "
                "Pass --user <email> or run createsuperuser first."
            )
        return user

    def _delete_demo_pages(self, user: User) -> None:
        slugs = [slug for slug, _title, _blocks in PAGES]
        qs = Page.objects.filter(user=user, slug__in=slugs)
        count = qs.count()
        qs.delete()
        if count:
            self.stdout.write(f"Removed {count} existing demo pages.")

    def _create_pages(self, user: User) -> Tuple[Dict[str, Page], int]:
        """Get-or-create every demo page. Returns (slug->Page, skipped_count)."""
        pages: Dict[str, Page] = {}
        skipped = 0
        for slug, title, _blocks in PAGES:
            page, created = Page.objects.get_or_create(
                user=user,
                slug=slug,
                defaults={
                    "title": title,
                    "page_type": "page",
                    "is_published": True,
                    "content": "",
                },
            )
            pages[slug] = page
            if not created:
                skipped += 1
        return pages, skipped

    def _create_blocks(self, user: User, pages: Dict[str, Page]) -> int:
        """Create blocks on each demo page and sync their hashtags."""
        created = 0
        for slug, _title, block_contents in PAGES:
            page = pages[slug]
            # Skip pages that already have blocks — avoids duplicating content
            # on repeated non-reset runs.
            if page.blocks.exists():
                continue
            for order, content in enumerate(block_contents):
                block = Block.objects.create(
                    user=user,
                    page=page,
                    content=content,
                    content_type="text",
                    block_type="bullet",
                    order=order,
                )
                self._sync_tags(user, block)
                created += 1
        return created

    def _sync_tags(self, user: User, block: Block) -> None:
        form = SyncBlockTagsForm(
            {
                "block": str(block.uuid),
                "content": block.content,
                "user": user.id,
            }
        )
        if form.is_valid():
            SyncBlockTagsCommand(form).execute()
