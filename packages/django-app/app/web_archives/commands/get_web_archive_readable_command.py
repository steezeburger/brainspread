from dataclasses import dataclass
from typing import Optional

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_web_archive_readable_form import GetWebArchiveReadableForm
from ..repositories import WebArchiveRepository


@dataclass
class ReadableArchivePayload:
    body: bytes
    mime_type: str


class GetWebArchiveReadableCommand(AbstractBaseCommand):
    """
    Return the stored readable bytes + mime type for a block's archive,
    or None when the block has no ready archive / its file is missing.
    Keeping storage + ownership concerns here lets the view stay a thin
    translation layer from HTTP to command input/output.
    """

    def __init__(self, form: GetWebArchiveReadableForm) -> None:
        self.form = form

    def execute(self) -> Optional[ReadableArchivePayload]:
        super().execute()
        user = self.form.cleaned_data["user"]
        block = self.form.cleaned_data["block"]

        archive = WebArchiveRepository.get_by_block_uuid(
            block_uuid=str(block.uuid), user=user
        )
        if archive is None or archive.readable_asset_id is None:
            return None

        asset = archive.readable_asset
        try:
            with asset.file.open("rb") as fh:
                body = fh.read()
        except FileNotFoundError:
            return None

        return ReadableArchivePayload(
            body=body,
            mime_type=asset.mime_type or "application/octet-stream",
        )
