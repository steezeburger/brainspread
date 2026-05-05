from typing import Any, Dict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_current_page_form import GetCurrentPageForm
from ..models import Page
from ..repositories import BlockRepository


class GetCurrentPageCommand(AbstractBaseCommand):
    """Return the page the user is currently viewing in the UI plus its
    root blocks. The page uuid comes from the chat request (set by the
    frontend), never from the LLM.
    """

    def __init__(self, form: GetCurrentPageForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        page: Page = self.form.cleaned_data["page"]
        root_blocks = BlockRepository.get_root_blocks(page)
        return {
            "page": {
                "uuid": str(page.uuid),
                "title": page.title,
                "slug": page.slug,
                "page_type": page.page_type,
                "date": page.date.isoformat() if page.date else None,
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
