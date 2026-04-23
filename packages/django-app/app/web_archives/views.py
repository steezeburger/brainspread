from typing import Dict, List, Optional, TypedDict

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from web_archives.commands import CaptureWebArchiveCommand, GetWebArchiveCommand
from web_archives.forms import CaptureWebArchiveForm, GetWebArchiveForm
from web_archives.models import WebArchiveData


class WebArchiveResponse(TypedDict):
    success: bool
    data: Optional[WebArchiveData]
    errors: Optional[Dict[str, List[str]]]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def capture_web_archive(request):
    """Kick off a capture for an existing block + URL and return the pending row."""
    try:
        data = request.data.copy()
        data["user"] = request.user.id
        form = CaptureWebArchiveForm(data)

        if form.is_valid():
            command = CaptureWebArchiveCommand(form)
            archive = command.execute()
            response: WebArchiveResponse = {
                "success": True,
                "data": archive.to_dict(),
                "errors": None,
            }
            return Response(response)

        response: WebArchiveResponse = {
            "success": False,
            "data": None,
            "errors": form.errors,
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

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
def get_web_archive(request, block_uuid: str):
    """Return the web archive for a block (for polling after capture)."""
    try:
        form = GetWebArchiveForm({"user": request.user.id, "block": block_uuid})
        if not form.is_valid():
            return Response(
                {"success": False, "data": None, "errors": form.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        archive = GetWebArchiveCommand(form).execute()
        if archive is None:
            return Response(
                {
                    "success": False,
                    "data": None,
                    "errors": {"block": ["No web archive"]},
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        response: WebArchiveResponse = {
            "success": True,
            "data": archive.to_dict(),
            "errors": None,
        }
        return Response(response)

    except Exception as e:
        return Response(
            {"success": False, "data": None, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
