import hashlib

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.upload_asset_form import UploadAssetForm
from ..models import Asset, file_type_from_mime
from ..repositories import AssetRepository


class UploadAssetCommand(AbstractBaseCommand):
    """
    Persist an uploaded file as an Asset, deduping against existing
    rows owned by the same user via sha256.

    The hash is computed by streaming the file through hashlib chunk by
    chunk so we don't load the whole upload into memory. Form-level
    validation has already enforced size + mime limits by the time we
    get here.
    """

    # 64KB. Big enough that hashing isn't dominated by Python overhead;
    # small enough to keep peak memory predictable for big uploads.
    _CHUNK_SIZE = 64 * 1024

    def __init__(self, form: UploadAssetForm) -> None:
        self.form = form

    def execute(self) -> Asset:
        super().execute()

        user = self.form.cleaned_data["user"]
        uploaded = self.form.cleaned_data["file"]
        asset_type = self.form.cleaned_data["asset_type"]
        source_url = self.form.cleaned_data.get("source_url") or ""

        sha256 = self._compute_sha256(uploaded)

        existing = AssetRepository.find_by_sha256(user=user, sha256=sha256)
        if existing is not None:
            # Same user re-uploading identical bytes - point at the
            # existing row rather than duplicating storage.
            return existing

        # Reset the cursor since _compute_sha256 walked it to EOF; the
        # FileField save needs to read from the start.
        uploaded.seek(0)

        mime_type = (
            (uploaded.content_type or "application/octet-stream")
            .split(";", 1)[0]
            .strip()
        )
        original_filename = uploaded.name or ""

        asset = Asset.objects.create(
            user=user,
            asset_type=asset_type,
            file_type=file_type_from_mime(mime_type),
            mime_type=mime_type,
            byte_size=uploaded.size,
            sha256=sha256,
            source_url=source_url,
            original_filename=original_filename,
        )
        asset.file.save(original_filename or str(asset.uuid), uploaded, save=True)
        return asset

    @classmethod
    def _compute_sha256(cls, uploaded) -> str:
        digest = hashlib.sha256()
        # UploadedFile.chunks() is the documented streaming iterator and
        # works for both in-memory and TemporaryUploadedFile.
        for chunk in uploaded.chunks(chunk_size=cls._CHUNK_SIZE):
            digest.update(chunk)
        return digest.hexdigest()
