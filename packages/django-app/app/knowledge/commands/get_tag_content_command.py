from typing import Any, Dict, List, Optional, TypedDict

from common.commands.abstract_base_command import AbstractBaseCommand
from core.models import User

from ..forms import GetTagContentForm
from ..models import BlockData, PageData
from ..repositories import BlockRepository, PageRepository


class GetTagContentCommand(AbstractBaseCommand):
    """Command to get all content associated with a specific tag (now using page-based tags)"""

    def __init__(self, form: GetTagContentForm) -> None:
        super().__init__()
        self.form = form

    def execute(self) -> Optional[Dict[str, Any]]:
        """Execute the command"""
        user: User = self.form.cleaned_data["user"]
        tag_name: str = self.form.cleaned_data["tag_name"]

        repository = PageRepository()

        # Look for tag page
        tag_page = repository.get_tag_page(tag_name, user)

        if not tag_page:
            return None

        # Get direct blocks (blocks that belong directly to this page)
        direct_blocks = tag_page.blocks.all().order_by("order")

        # Get referenced blocks (blocks from other pages that reference this
        # tag). Descendants whose ancestor is also tagged are dropped so they
        # aren't shown twice — once nested, once standalone.
        referenced_blocks = BlockRepository.get_referenced_blocks(tag_page)

        # Get all pages that have blocks with this tag (excluding the tag page itself)
        pages = []
        for block in referenced_blocks:
            if block.page != tag_page and block.page not in pages:
                pages.append(block.page)

        return {
            "tag_page": tag_page,
            "direct_blocks": direct_blocks,
            "referenced_blocks": referenced_blocks,
            "pages": pages,
        }


class TagContentData(TypedDict):
    tag_page: PageData
    blocks: List[BlockData]
    pages: List[PageData]
    total_blocks: int
    total_pages: int
    total_content: int
