from typing import Dict, List, Optional, TypedDict

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .commands import GetAssetCommand, UploadAssetCommand
from .forms import GetAssetForm, UploadAssetForm
from .models import AssetData


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
    Stream the bytes for a user-owned asset. Routed through Django (not
    via MEDIA_URL) so we can enforce per-request ownership - a public
    /media/<path>/ would leak any file to anyone who guessed the path.
    Returns 404 for both missing and not-owned-by-this-user, so the
    response shape doesn't reveal whether the uuid exists.
    """
    form = GetAssetForm({"user": request.user.id, "uuid": asset_uuid})
    if not form.is_valid():
        raise Http404("asset not found")

    payload = GetAssetCommand(form).execute()
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
