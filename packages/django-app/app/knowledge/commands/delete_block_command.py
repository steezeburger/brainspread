from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.forms.delete_block_form import DeleteBlockForm
from knowledge.forms.touch_page_form import TouchPageForm
from web_archives.commands import SoftDeleteWebArchiveCommand
from web_archives.forms import SoftDeleteWebArchiveForm

from .touch_page_command import TouchPageCommand


class DeleteBlockCommand(AbstractBaseCommand):
    """Command to delete a block"""

    def __init__(self, form: DeleteBlockForm) -> None:
        self.form = form

    def execute(self) -> bool:
        """Execute the command"""
        super().execute()  # This validates the form

        block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]

        # Archive cleanup runs before the block delete so the archive's
        # OneToOne link still resolves. Soft-delete preserves the stored
        # bytes (see web_archives.WebArchive for the durability contract).
        archive_form = SoftDeleteWebArchiveForm(
            {"user": user.id, "block": str(block.uuid)}
        )
        if archive_form.is_valid():
            SoftDeleteWebArchiveCommand(archive_form).execute()

        # Capture the page reference before the delete cascades — afterwards
        # block.page would still resolve from the unsaved instance, but we
        # want the explicit local for clarity.
        page = block.page
        block.delete()

        touch_form = TouchPageForm(data={"user": user.id, "page": str(page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return True
