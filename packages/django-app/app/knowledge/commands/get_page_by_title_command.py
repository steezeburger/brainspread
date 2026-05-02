from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_page_by_title_form import GetPageByTitleForm
from ..repositories.block_repository import BlockRepository
from ..repositories.page_repository import PageRepository


class GetPageByTitleCommand(AbstractBaseCommand):
    """Look up a page by case-insensitive title and return it with its
    root blocks. Returns {"error": ...} when no page matches so the
    assistant can react without raising.
    """

    def __init__(self, form: GetPageByTitleForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        title = self.form.cleaned_data["title"].strip()

        page = (
            PageRepository.get_queryset().filter(user=user, title__iexact=title).first()
        )
        if not page:
            return {"error": f"No page found with title '{title}'"}

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
