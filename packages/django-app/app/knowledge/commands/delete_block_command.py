from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.forms.delete_block_form import DeleteBlockForm
from web_archives.commands import SoftDeleteWebArchiveCommand
from web_archives.forms import SoftDeleteWebArchiveForm


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

        block.delete()
        return True
