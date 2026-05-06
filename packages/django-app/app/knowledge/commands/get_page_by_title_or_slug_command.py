from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_page_by_title_or_slug_form import GetPageByTitleOrSlugForm
from ..repositories.block_repository import BlockRepository
from ..repositories.page_repository import PageRepository


class GetPageByTitleOrSlugCommand(AbstractBaseCommand):
    """Look up a page by case-insensitive title OR slug, returning it
    with its root blocks. Returns {"error": ...} when no page matches
    so the assistant can react without raising.

    Title takes precedence — if a title and a slug collide on the same
    string the title-matching page wins. Both lookups are scoped to
    the user via the repository.
    """

    def __init__(self, form: GetPageByTitleOrSlugForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        query = self.form.cleaned_data["query"].strip()

        page = PageRepository.get_by_title_or_slug(user, query)
        if not page:
            return {"error": f"No page found matching '{query}'"}

        root_blocks = BlockRepository.get_root_blocks(page)
        return {
            "page": {
                "uuid": str(page.uuid),
                "title": page.title,
                "slug": page.slug,
                "page_type": page.page_type,
            },
            "blocks": [
                {
                    "block_uuid": str(block.uuid),
                    "block_type": block.block_type,
                    "content": block.content,
                    "order": block.order,
                }
                for block in root_blocks
            ],
        }
