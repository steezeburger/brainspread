from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.repositories.block_repository import BlockRepository

from ..forms.delete_page_form import DeletePageForm


class DeletePageCommand(AbstractBaseCommand):
    """Archive a page: soft-deletes the page and every block on it.

    The page row survives (is_active=False, deleted_at stamped — see
    SoftDeleteTimestampMixin) so it can be restored from the Trash view.
    Its blocks are soft-deleted alongside it so they drop out of every
    block query (search, saved views, backlinks, due/overdue) without
    those call sites having to filter on the page's active state — see
    BlockRepository.soft_delete_page_blocks.
    """

    def __init__(self, form: DeletePageForm) -> None:
        self.form = form

    def execute(self) -> bool:
        """Execute the command"""
        super().execute()  # This validates the form

        page = self.form.cleaned_data["page"]
        with transaction.atomic():
            BlockRepository.soft_delete_page_blocks(page)
            page.delete()
        return True
