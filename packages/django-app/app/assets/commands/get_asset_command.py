from dataclasses import dataclass
from typing import Optional

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_asset_form import GetAssetForm
from ..repositories import AssetRepository


@dataclass
class AssetPayload:
    body: bytes
    mime_type: str
    original_filename: str


class GetAssetCommand(AbstractBaseCommand):
    """
    Resolve and read the bytes for an asset owned by a given user.
    Returns None when the asset doesn't exist, isn't owned by the user,
    or its file is missing on disk - the caller (an HTTP view) maps
    None to a 404.
    """

    def __init__(self, form: GetAssetForm) -> None:
        self.form = form

    def execute(self) -> Optional[AssetPayload]:
        super().execute()
        user = self.form.cleaned_data["user"]
        uuid = self.form.cleaned_data["uuid"]

        asset = AssetRepository.get_by_uuid(uuid=str(uuid), user=user)
        if asset is None or not asset.file:
            return None

        try:
            with asset.file.open("rb") as fh:
                body = fh.read()
        except FileNotFoundError:
            return None

        return AssetPayload(
            body=body,
            mime_type=asset.mime_type or "application/octet-stream",
            original_filename=asset.original_filename or "",
        )
