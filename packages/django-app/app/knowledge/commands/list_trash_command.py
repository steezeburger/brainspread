from typing import List, TypedDict

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_trash_form import ListTrashForm
from ..models.block import BlockData
from ..models.page import PageData
from ..repositories import BlockRepository, PageRepository

DEFAULT_LIMIT = 50


class TrashPageData(PageData):
    deleted_at: str


class TrashBlockData(BlockData):
    deleted_at: str


class TrashData(TypedDict):
    pages: List[TrashPageData]
    blocks: List[TrashBlockData]


class ListTrashCommand(AbstractBaseCommand):
    """The user's Trash: soft-deleted pages and blocks, each ordered by
    most-recently-deleted first. v1 is a flat list per issue #122; no
    search/filtering yet."""

    def __init__(self, form: ListTrashForm) -> None:
        self.form = form

    def execute(self) -> TrashData:
        super().execute()

        user = self.form.cleaned_data["user"]
        limit = self.form.cleaned_data.get("limit") or DEFAULT_LIMIT

        pages: List[TrashPageData] = []
        for page in PageRepository.get_deleted_pages(user, limit=limit):
            data: TrashPageData = {
                **page.to_dict(),
                "deleted_at": page.deleted_at.isoformat(),
            }
            pages.append(data)

        blocks: List[TrashBlockData] = []
        for block in BlockRepository.get_deleted_blocks(user, limit=limit):
            data: TrashBlockData = {
                **block.to_dict(include_page_context=True),
                "deleted_at": block.deleted_at.isoformat(),
            }
            blocks.append(data)

        return {"pages": pages, "blocks": blocks}
