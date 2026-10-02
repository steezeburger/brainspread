from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.repositories.block_repository import BlockRepository

from ..forms.restore_page_form import RestorePageForm


class RestorePageCommand(AbstractBaseCommand):
    """Restore a soft-deleted page and every block that was soft-deleted
    alongside it (see DeletePageCommand's cascade)."""

    def __init__(self, form: RestorePageForm) -> None:
        self.form = form

    def execute(self) -> bool:
        super().execute()

        page = self.form.cleaned_data["page"]
        with transaction.atomic():
            page.undelete()
            BlockRepository.restore_page_blocks(page)
        return True
