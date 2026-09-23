from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.forms.touch_page_form import TouchPageForm
from knowledge.repositories.block_repository import BlockRepository

from ..forms.restore_block_form import RestoreBlockForm
from .touch_page_command import TouchPageCommand


class RestoreBlockCommand(AbstractBaseCommand):
    """Restore a soft-deleted block and its descendant subtree."""

    def __init__(self, form: RestoreBlockForm) -> None:
        self.form = form

    def execute(self) -> bool:
        super().execute()

        block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]

        BlockRepository.restore_subtree(block)

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return True
