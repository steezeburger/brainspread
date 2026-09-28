from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.soft_delete_web_archives_for_blocks_form import (
    SoftDeleteWebArchivesForBlocksForm,
)
from ..repositories import WebArchiveRepository


class SoftDeleteWebArchivesForBlocksCommand(AbstractBaseCommand):
    """
    Soft-delete the archive row owned by each block in the list, in one
    query. No-op for blocks with no archive. Bytes on disk are
    preserved; only each archive's is_active flag flips and deleted_at
    gets stamped. Called by DeleteBlockCommand as part of the
    cross-app subtree-deletion flow.
    """

    def __init__(self, form: SoftDeleteWebArchivesForBlocksForm) -> None:
        self.form = form

    def execute(self) -> int:
        super().execute()
        user = self.form.cleaned_data["user"]
        block_uuids = self.form.cleaned_data["block_uuids"]

        return WebArchiveRepository.soft_delete_for_blocks(block_uuids, user)
