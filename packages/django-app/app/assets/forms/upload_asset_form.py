import os

from django import forms
from django.conf import settings

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Asset

# Extensions that browsers commonly upload as application/octet-stream
# because the OS MIME database doesn't know about them. We treat these
# as text/plain so they pass the `text/*` whitelist; the original
# filename is preserved separately on the Asset row.
_TEXT_LIKE_EXTENSIONS = {
    ".mmd": "text/plain",
    ".mermaid": "text/plain",
}


class UploadAssetForm(BaseForm):
    """
    Validate a multipart asset upload. Cheap checks (size, mime
    whitelist) live here; the streaming sha256 + dedupe + Asset row
    creation happens in UploadAssetCommand so the form stays a pure
    validator.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    file = forms.FileField()
    asset_type = forms.ChoiceField(
        choices=Asset.ASSET_TYPE_CHOICES,
        required=False,
    )
    source_url = forms.URLField(max_length=2048, required=False)

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise forms.ValidationError("User is required")
        return user

    def clean_file(self):
        uploaded = self.cleaned_data.get("file")
        if uploaded is None:
            raise forms.ValidationError("File is required")

        max_bytes = settings.ASSET_UPLOAD_MAX_BYTES
        if uploaded.size > max_bytes:
            raise forms.ValidationError(
                f"File too large ({uploaded.size} bytes); "
                f"maximum is {max_bytes} bytes"
            )

        # content_type can include parameters (e.g. "text/html; charset=utf-8");
        # only the bare type counts for the whitelist check.
        content_type = (uploaded.content_type or "").split(";", 1)[0].strip().lower()

        # Normalize for known text-shaped extensions that browsers don't
        # have a MIME for. Mutate the upload so the downstream command
        # records the corrected type rather than `application/octet-stream`.
        if content_type in ("", "application/octet-stream"):
            ext = os.path.splitext(uploaded.name or "")[1].lower()
            override = _TEXT_LIKE_EXTENSIONS.get(ext)
            if override:
                content_type = override
                uploaded.content_type = override

        whitelist = settings.ASSET_UPLOAD_MIME_WHITELIST
        if whitelist and not _mime_matches_whitelist(content_type, whitelist):
            raise forms.ValidationError(
                f"Unsupported file type: {content_type or 'unknown'}"
            )

        return uploaded


def _mime_matches_whitelist(content_type: str, whitelist) -> bool:
    """
    Check `content_type` against a whitelist that may contain literal
    MIME strings ("image/png") or `prefix/*` wildcards ("text/*").

    The wildcard form lets us accept text-shaped uploads
    (text/plain, text/csv, text/x-python, text/x-shellscript, ...) in
    one entry rather than enumerating every code extension's MIME -
    browsers are inconsistent about which one they send for a given
    extension and we'd otherwise reject perfectly reasonable files.
    """
    if not content_type:
        return False
    for entry in whitelist:
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry.endswith("/*"):
            prefix = entry[:-1]  # keep the trailing slash so "text/" matches
            if content_type.startswith(prefix):
                return True
        elif entry == content_type:
            return True
    return False
