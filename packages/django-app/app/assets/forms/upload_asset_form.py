from django import forms
from django.conf import settings

from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Asset


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

        whitelist = settings.ASSET_UPLOAD_MIME_WHITELIST
        # content_type can include parameters (e.g. "text/html; charset=utf-8");
        # only the bare type counts for the whitelist check.
        content_type = (uploaded.content_type or "").split(";", 1)[0].strip().lower()
        if whitelist and content_type not in whitelist:
            raise forms.ValidationError(
                f"Unsupported file type: {content_type or 'unknown'}"
            )

        return uploaded

    def clean_asset_type(self) -> str:
        # Default to a generic "upload" when the caller doesn't specify.
        # Consumer-specific endpoints (block paste, whiteboard insert, chat
        # attach) can pass a more precise asset_type when they know it.
        return self.cleaned_data.get("asset_type") or Asset.ASSET_TYPE_UPLOAD
