from typing import Optional

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_web_archive_form import GetWebArchiveForm
from ..models import WebArchive
from ..repositories import WebArchiveRepository


class GetWebArchiveCommand(AbstractBaseCommand):
    """Fetch the web archive for a block, or None if capture never started."""

    def __init__(self, form: GetWebArchiveForm) -> None:
        self.form = form

    def execute(self) -> Optional[WebArchive]:
        super().execute()
        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]
        return WebArchiveRepository.get_by_block_uuid(
            block_uuid=str(block.uuid), user=user
        )
