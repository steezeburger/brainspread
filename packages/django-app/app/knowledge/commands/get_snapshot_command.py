from typing import Optional

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_snapshot_form import GetSnapshotForm
from ..models import Snapshot
from ..repositories import SnapshotRepository


class GetSnapshotCommand(AbstractBaseCommand):
    """Fetch the snapshot for a block, or None if capture was never started."""

    def __init__(self, form: GetSnapshotForm) -> None:
        self.form = form

    def execute(self) -> Optional[Snapshot]:
        super().execute()
        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]
        return SnapshotRepository.get_by_block_uuid(
            block_uuid=str(block.uuid), user=user
        )
