import hashlib

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.upload_asset_form import UploadAssetForm
from ..models import Asset, file_type_from_mime
from ..repositories import AssetRepository

# 64 KB. Big enough that hashing isn't dominated by Python overhead;
# small enough to keep peak memory predictable for big uploads.
_SHA256_CHUNK_SIZE = 64 * 1024


def _compute_sha256(uploaded) -> str:
    """
    Hex sha256 of an UploadedFile, computed by streaming through
    hashlib chunk by chunk so we don't pull the whole upload into
    memory. Walks the file cursor to EOF; callers must seek(0) before
    reusing the stream.
    """
    digest = hashlib.sha256()
    # UploadedFile.chunks() is the documented streaming iterator and
    # works for both in-memory and TemporaryUploadedFile.
    for chunk in uploaded.chunks(chunk_size=_SHA256_CHUNK_SIZE):
        digest.update(chunk)
    return digest.hexdigest()


class UploadAssetCommand(AbstractBaseCommand):
    """
    Persist an uploaded file as an Asset, deduping against existing
    rows owned by the same user via sha256. Form-level validation has
    already enforced size + mime limits by the time we get here.
    """

    def __init__(self, form: UploadAssetForm) -> None:
        self.form = form

    def execute(self) -> Asset:
        super().execute()

        user = self.form.cleaned_data["user"]
        uploaded = self.form.cleaned_data["file"]
        # BaseForm.clean() drops fields that weren't submitted, so we
        # default here rather than relying on clean_asset_type's default.
        asset_type = self.form.cleaned_data.get("asset_type") or Asset.ASSET_TYPE_UPLOAD
        source_url = self.form.cleaned_data.get("source_url") or ""

        sha256 = _compute_sha256(uploaded)

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
