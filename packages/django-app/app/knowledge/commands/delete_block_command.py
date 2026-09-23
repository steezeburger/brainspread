from common.commands.abstract_base_command import AbstractBaseCommand
from knowledge.forms.delete_block_form import DeleteBlockForm
from knowledge.forms.touch_page_form import TouchPageForm
from knowledge.repositories.block_repository import BlockRepository
from web_archives.commands import SoftDeleteWebArchiveCommand
from web_archives.forms import SoftDeleteWebArchiveForm

from .touch_page_command import TouchPageCommand


class DeleteBlockCommand(AbstractBaseCommand):
    """Command to delete a block and its descendant subtree"""

    def __init__(self, form: DeleteBlockForm) -> None:
        self.form = form

    def execute(self) -> bool:
        """Execute the command"""
        super().execute()  # This validates the form

        block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]

        # The whole subtree soft-deletes together, so clean up the archive
        # of every member (not just the root) the same way a single-block
        # delete always has — see web_archives.WebArchive for the
        # durability contract.
        subtree = [block] + BlockRepository.get_block_descendants(block)
        for member in subtree:
            archive_form = SoftDeleteWebArchiveForm(
                {"user": user.id, "block": str(member.uuid)}
            )
            if archive_form.is_valid():
                SoftDeleteWebArchiveCommand(archive_form).execute()

        # Capture the page reference before the delete — afterwards
        # block.page would still resolve from the unsaved instance, but we
        # want the explicit local for clarity.
        page = block.page
        BlockRepository.soft_delete_subtree(block)

        touch_form = TouchPageForm(data={"user": user.id, "page": str(page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return True
