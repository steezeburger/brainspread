import uuid as uuid_lib
from typing import Dict, List, Optional, TypedDict

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .commands import AssetPayload, GetAssetCommand, UploadAssetCommand
from .forms import GetAssetForm, UploadAssetForm
from .models import AssetData
from .repositories import AssetRepository


class UploadAssetResponse(TypedDict):
    success: bool
    data: Optional[AssetData]
    errors: Optional[Dict[str, List[str]]]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_asset(request):
    """
    Multipart upload endpoint. Accepts a file plus optional
    asset_type / source_url, dedupes by sha256, and returns the asset
    metadata. The actual file bytes are served by `serve_asset` below
    rather than via a public MEDIA_URL so ownership stays on the
    request path.
    """
    try:
        # request.data carries form fields; request.FILES carries uploads.
        # BaseForm needs them as separate dicts because FileField pulls
        # from `self.files`, not `self.data`.
        data = {k: v for k, v in request.data.items() if k not in request.FILES}
        data["user"] = request.user.id
        form = UploadAssetForm(data, files=request.FILES)

        if form.is_valid():
            asset = UploadAssetCommand(form).execute()
            response: UploadAssetResponse = {
                "success": True,
                "data": asset.to_dict(),
                "errors": None,
            }
            return Response(response)

        return Response(
            {"success": False, "data": None, "errors": form.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except ValidationError as e:
        return Response(
            {"success": False, "data": None, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        return Response(
            {"success": False, "data": None, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def serve_asset(request, asset_uuid: str):
    """
    Stream the bytes for an asset. Routed through Django (not via
    MEDIA_URL) so we can enforce per-request ownership - a public
    /media/<path>/ would leak any file to anyone who guessed the path.

    Access policy:
      - Owner: can read their own assets.
      - Staff (Django admin): can read any asset, for preview /
        moderation. Admin already has unrestricted DB access through
        the admin UI; gating the bytes behind owner-only would just
        force admins to dig into MEDIA_ROOT manually instead.
      - Everyone else: 404, indistinguishable from a missing uuid so
        the response shape doesn't reveal whether the uuid exists.
    """
    if request.user.is_staff:
        payload = _staff_payload(asset_uuid)
    else:
        form = GetAssetForm({"user": request.user.id, "uuid": asset_uuid})
        payload = GetAssetCommand(form).execute() if form.is_valid() else None

    if payload is None:
        raise Http404("asset not found")

    response = HttpResponse(payload.body, content_type=payload.mime_type)
    # Inline so images / PDFs render in the browser; the browser will
    # still respect Content-Disposition: attachment for save-as flows
    # if a future endpoint needs a force-download variant.
    if payload.original_filename:
        response["Content-Disposition"] = (
            f'inline; filename="{payload.original_filename}"'
        )
    else:
        response["Content-Disposition"] = "inline"
    return response


def _staff_payload(asset_uuid: str) -> Optional[AssetPayload]:
    """
    Look up an asset by uuid without an owner filter. Used by staff
    callers (admin preview); regular users go through GetAssetCommand
    which keeps the per-user check.
    """
    try:
        uuid_lib.UUID(asset_uuid)
    except (TypeError, ValueError):
        return None
    asset = AssetRepository.get_by_uuid(uuid=asset_uuid, user=None)
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
