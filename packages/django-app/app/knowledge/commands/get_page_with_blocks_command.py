from typing import List, Tuple

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.models import (
    SYSTEM_VIEW_OVERDUE,
    Block,
    Page,
    PageEmbeddedView,
)
from knowledge.repositories import (
    BlockRepository,
    PageEmbeddedViewRepository,
    PageRepository,
    SavedViewRepository,
)
from knowledge.services import query_engine

from ..forms.get_page_with_blocks_form import GetPageWithBlocksForm
from ..services.system_views import seed_system_views_for_user


class GetPageWithBlocksCommand(AbstractBaseCommand):
    """Command to get a page with all its blocks (and pinned embeds).

    Returns ``(page, direct_blocks, referenced_blocks, overdue_blocks,
    embedded_views)``. The Overdue block list remains a parallel
    pre-rendered section (full-fidelity BlockComponent) so users can
    still mark items done from the daily page without going to the
    source. Embedded views are the saved-view widgets pinned above
    the bullet area.
    """

    def __init__(self, form: GetPageWithBlocksForm) -> None:
        self.form = form

    def execute(
        self,
    ) -> Tuple[Page, List[Block], List[Block], List[Block], List[PageEmbeddedView]]:
        super().execute()

        user = self.form.cleaned_data.get("user")
        page = self.form.cleaned_data.get("page")
        date = self.form.cleaned_data.get("date")
        slug = self.form.cleaned_data.get("slug")

        today = user.today()

        if slug:
            # Get regular page by slug
            page = PageRepository.get_by_slug(slug, user)
            if not page:
                raise ValidationError(f"Page with slug '{slug}' not found")
        elif date:
            # Get or create daily note
            page, created = PageRepository.get_or_create_daily_note(user, date)
        elif not page:
            # Default to today's daily note (in the user's timezone).
            page, created = PageRepository.get_or_create_daily_note(user, today)

        # Get direct blocks (blocks that belong directly to this page)
        direct_blocks = BlockRepository.get_root_blocks(page)

        # Get referenced blocks (blocks from other pages that reference this
        # page via the M2M tag relationship). Descendants whose ancestor is
        # also tagged are dropped — they already render nested under that
        # ancestor's reference, so a standalone entry would just duplicate.
        referenced_blocks = BlockRepository.get_referenced_blocks(page)

        overdue_blocks: List[Block] = []
        if page.page_type == "daily" and page.date == today:
            overdue_blocks = self._fetch_overdue_via_system_view(user)

        embedded_views = list(PageEmbeddedViewRepository.list_for_page(page))

        return (
            page,
            list(direct_blocks),
            list(referenced_blocks),
            overdue_blocks,
            embedded_views,
        )

    def _fetch_overdue_via_system_view(self, user) -> List[Block]:
        """Run the seeded ``overdue`` SavedView for the user.

        Lazily seeds the system views if the user predates the seed
        migration somehow (the migration backfilled existing users, but
        defensive: missing seed shouldn't 500 the daily page). On a
        compile error we fall through to an empty list rather than break
        the page render.
        """
        view = SavedViewRepository.get_system_view(SYSTEM_VIEW_OVERDUE, user=user)
        if view is None:
            seed_system_views_for_user(user)
            view = SavedViewRepository.get_system_view(SYSTEM_VIEW_OVERDUE, user=user)
        if view is None:
            return []
        try:
            compiled = query_engine.compile(view.filter, user=user, sort=view.sort)
        except query_engine.QueryEngineError:
            return []
        return list(BlockRepository.run_compiled_query(user, compiled))
