from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.soft_delete_web_archive_form import SoftDeleteWebArchiveForm
from ..repositories import WebArchiveRepository


class SoftDeleteWebArchiveCommand(AbstractBaseCommand):
    """
    Soft-delete the archive row owned by a block. No-op if the block has
    no archive. Bytes on disk are preserved; only the archive's is_active
    flag flips and deleted_at gets stamped. Called by DeleteBlockCommand
    as part of the cross-app deletion flow.
    """

    def __init__(self, form: SoftDeleteWebArchiveForm) -> None:
        self.form = form

    def execute(self) -> bool:
        super().execute()
        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]

        archive = WebArchiveRepository.get_by_block_uuid(
            block_uuid=str(block.uuid), user=user
        )
        if archive is None:
            return False

        # SoftDeleteTimestampMixin.delete() sets is_active=False +
        # deleted_at=now() and saves the row (without removing it).
        archive.delete()
        return True
