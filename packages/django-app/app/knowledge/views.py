import re
from typing import Dict, List, Optional, TypedDict

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from assets.models import Asset
from knowledge.commands import (
    BulkDeleteBlocksCommand,
    BulkMoveBlocksCommand,
    ConsumeReminderActionCommand,
    CreateBlockCommand,
    CreatePageCommand,
    DeleteBlockCommand,
    DeletePageCommand,
    GetFavoritedPagesCommand,
    GetGraphDataCommand,
    GetHistoricalDataCommand,
    GetPageWithBlocksCommand,
    GetTagContentCommand,
    GetUserPagesCommand,
    MoveBlockToDailyCommand,
    MoveUndoneTodosCommand,
    ReorderBlocksCommand,
    ScheduleBlockCommand,
    SearchNotesCommand,
    SearchPagesCommand,
    SetPageFavoritedCommand,
    SharePageCommand,
    ToggleBlockTodoCommand,
    UpdateBlockCommand,
    UpdatePageCommand,
)
from knowledge.commands.bulk_delete_blocks_command import BulkDeleteBlocksData
from knowledge.commands.bulk_move_blocks_command import BulkMoveBlocksData
from knowledge.commands.get_graph_data_command import GraphData
from knowledge.commands.get_historical_data_command import HistoricalData
from knowledge.commands.get_tag_content_command import TagContentData
from knowledge.commands.move_block_to_daily_command import MoveBlockToDailyData
from knowledge.commands.move_undone_todos_command import MoveUndoneTodosData
from knowledge.forms import (
    BulkDeleteBlocksForm,
    BulkMoveBlocksForm,
    ConsumeReminderActionForm,
    CreateBlockForm,
    CreatePageForm,
    DeleteBlockForm,
    DeletePageForm,
    GetFavoritedPagesForm,
    GetGraphDataForm,
    GetHistoricalDataForm,
    GetPageWithBlocksForm,
    GetTagContentForm,
    GetUserPagesForm,
    MoveBlockToDailyForm,
    MoveUndoneTodosForm,
    ReorderBlocksForm,
    ScheduleBlockForm,
    SearchNotesForm,
    SearchPagesForm,
    SetPageFavoritedForm,
    SharePageForm,
    ToggleBlockTodoForm,
    UpdateBlockForm,
    UpdatePageForm,
)
from knowledge.models import BlockData, Page, PageData, PagesData
from knowledge.models.page import PageWithBlocksData
from knowledge.repositories import BlockRepository


# API Response Types with specific data types
class PageResponse(TypedDict):
    success: bool
    data: Optional[PageData]
    errors: Optional[Dict[str, List[str]]]


class PagesResponse(TypedDict):
    success: bool
    data: Optional[PagesData]
    errors: Optional[Dict[str, List[str]]]


class BlockResponse(TypedDict):
    success: bool
    data: Optional[BlockData]
    errors: Optional[Dict[str, List[str]]]


class DeleteResponse(TypedDict):
    success: bool
    data: Optional[Dict[str, str]]
    errors: Optional[Dict[str, List[str]]]


class GetHistoricalDataResponse(TypedDict):
    success: bool
    data: Optional[HistoricalData]
    errors: Optional[Dict[str, List[str]]]


class GetTagContentResponse(TypedDict):
    success: bool
    data: Optional[TagContentData]
    errors: Optional[Dict[str, List[str]]]


class GetPageWithBlocksResponse(TypedDict):
    success: bool
    data: Optional[PageWithBlocksData]
    errors: Optional[Dict[str, List[str]]]


class MoveUndoneTodosResponse(TypedDict):
    success: bool
    data: Optional[MoveUndoneTodosData]
    errors: Optional[Dict[str, List[str]]]


class MoveBlockToDailyResponse(TypedDict):
    success: bool
    data: Optional[MoveBlockToDailyData]
    errors: Optional[Dict[str, List[str]]]


class GraphDataResponse(TypedDict):
    success: bool
    data: Optional[GraphData]
    errors: Optional[Dict[str, List[str]]]


class BulkDeleteBlocksResponse(TypedDict):
    success: bool
    data: Optional[BulkDeleteBlocksData]
    errors: Optional[Dict[str, List[str]]]


class BulkMoveBlocksResponse(TypedDict):
    success: bool
    data: Optional[BulkMoveBlocksData]
    errors: Optional[Dict[str, List[str]]]


def index(request, date=None, tag_name=None, slug=None):
    # The HTML shell references hashed/versioned asset URLs, so it must
    # never be cached - otherwise mobile browsers keep serving stale script
    # tags and never pick up new deploys.
    response = render(request, "knowledge/index.html")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def _public_asset_url(share_token: str, asset_uuid: str) -> str:
    """Build the public, no-auth asset URL the share template should use."""
    return f"/knowledge/share/{share_token}/asset/{asset_uuid}/"


# Editor-side asset URLs look like "/api/assets/<uuid>/" and require auth.
# The public view rewrites them to a token-scoped sibling that resolves
# only for assets referenced by the currently shared page.
_AUTHED_ASSET_URL = re.compile(r"/api/assets/([0-9a-fA-F-]{32,36})/")


def _rewrite_asset_urls(content: str, share_token: str) -> str:
    """Rewrite editor /api/assets/<uuid>/ URLs to the token-scoped public path.

    Block content can embed image markdown like
    ![](/api/assets/<uuid>/) — those URLs would 401 for anonymous viewers.
    The public path checks both that the share is active AND that the
    asset is referenced by the page, so this rewrite doesn't widen access.
    """
    if not content:
        return content
    return _AUTHED_ASSET_URL.sub(
        lambda m: _public_asset_url(share_token, m.group(1)), content
    )


def _serialize_block_tree(block, share_token: str) -> dict:
    """Render a block + its descendants as a plain dict tree for the public
    template. Strips fields the public template doesn't need so we don't
    accidentally leak owner-only metadata (reminders, asset internals, etc.).
    """
    asset_uuid = str(block.asset.uuid) if block.asset_id else None
    asset_file_type = block.asset.file_type if block.asset_id else None
    return {
        "uuid": str(block.uuid),
        "content": _rewrite_asset_urls(block.content, share_token),
        "block_type": block.block_type,
        "content_type": block.content_type,
        "media_url": block.media_url,
        "asset_url": (
            _public_asset_url(share_token, asset_uuid) if asset_uuid else None
        ),
        "asset_is_image": asset_file_type == "image",
        "children": [
            _serialize_block_tree(child, share_token) for child in block.get_children()
        ],
    }


def _serialize_referenced_block(block, share_token: str) -> dict:
    """Flat dict for a block that lives on another page but is tagged with
    the shared page. Carries source-page context so the template can
    label "from <daily date> / <page title>" without exposing a working
    link to the source page.

    Renders flat (no children) to match how the editor surfaces linked
    references — the recipient sees the same scope of content the owner
    sees in their own "Linked References" section.
    """
    asset_uuid = str(block.asset.uuid) if block.asset_id else None
    asset_file_type = block.asset.file_type if block.asset_id else None
    source = block.page
    return {
        "uuid": str(block.uuid),
        "content": _rewrite_asset_urls(block.content, share_token),
        "block_type": block.block_type,
        "content_type": block.content_type,
        "media_url": block.media_url,
        "asset_url": (
            _public_asset_url(share_token, asset_uuid) if asset_uuid else None
        ),
        "asset_is_image": asset_file_type == "image",
        "source_page_title": source.title if source else "",
        "source_page_type": source.page_type if source else "",
        "source_page_date": (
            source.date.isoformat() if source and source.date else None
        ),
    }


def public_page(request, share_token: str):
    """Public, no-auth read-only view of a shared page. Resolves the
    share_token to a Page only if its current share_mode is "link" —
    flipping back to private breaks all outstanding links immediately.
    """
    try:
        page = Page.objects.get(share_token=share_token)
    except Page.DoesNotExist:
        raise Http404("Shared page not found")

    if not page.is_publicly_viewable:
        raise Http404("Shared page not found")

    blocks = [
        _serialize_block_tree(b, share_token)
        for b in BlockRepository.get_root_blocks(page)
    ]
    # Linked references — blocks elsewhere that tag this page (e.g. daily
    # notes that mention #food-log). For a topic / tag-style page these
    # ARE the content, so the share view would be empty without them.
    referenced_blocks = (
        page.tagged_blocks.exclude(page=page)
        .select_related("user", "page", "asset")
        .order_by("-page__date", "-modified_at", "order")
    )
    references = [
        _serialize_referenced_block(b, share_token) for b in referenced_blocks
    ]

    response = render(
        request,
        "knowledge/public_page.html",
        {
            "page": page,
            "blocks": blocks,
            "references": references,
            "owner_email": page.user.email,
        },
    )
    # Public pages can be cached briefly by the browser, but always revalidate
    # — owners can revoke or edit at any time.
    response["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    return response


def public_asset(request, share_token: str, asset_uuid: str):
    """Public, no-auth asset bytes for assets referenced by a shared page.

    The asset must satisfy two conditions to resolve:
      1. The share_token belongs to a page whose current share_mode is
         "link" (private = revoked, immediate 404).
      2. Some block on that page references the asset (FK match) — or
         embeds it in content via /api/assets/<uuid>/. This stops a
         malicious viewer from substituting an unrelated asset_uuid into
         the URL to read other content the owner hasn't actually shared.
    """
    try:
        page = Page.objects.get(share_token=share_token)
    except Page.DoesNotExist:
        raise Http404("Shared asset not found")

    if not page.is_publicly_viewable:
        raise Http404("Shared asset not found")

    try:
        asset = Asset.objects.get(uuid=asset_uuid, user=page.user)
    except (Asset.DoesNotExist, ValueError, ValidationError):
        raise Http404("Shared asset not found")

    # An asset is considered "shared" if any block visible on the public
    # page uses it. That includes both blocks living on the page itself
    # (page.blocks) and blocks tagged with the page (page.tagged_blocks)
    # — the public render shows both, so both must be able to load images.
    inline_marker = f"/api/assets/{asset_uuid}/"
    direct_match = (
        page.blocks.filter(asset=asset).exists()
        or page.blocks.filter(content__contains=inline_marker).exists()
    )
    tagged_match = (
        page.tagged_blocks.filter(asset=asset).exists()
        or page.tagged_blocks.filter(content__contains=inline_marker).exists()
    )
    if not (direct_match or tagged_match):
        raise Http404("Shared asset not found")

    if not asset.file:
        raise Http404("Shared asset not found")

    try:
        with asset.file.open("rb") as fh:
            body = fh.read()
    except FileNotFoundError:
        raise Http404("Shared asset not found")

    response = HttpResponse(
        body, content_type=asset.mime_type or "application/octet-stream"
    )
    if asset.original_filename:
        response["Content-Disposition"] = (
            f'inline; filename="{asset.original_filename}"'
        )
    else:
        response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "no-cache, must-revalidate, max-age=0"
    return response


# Page management endpoints
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_page(request):
    """API endpoint to create page"""
    try:
        data = request.data
        data["user"] = request.user.id
        form = CreatePageForm(data)

        if form.is_valid():
            command = CreatePageCommand(form)
            page = command.execute()

            response: PageResponse = {
                "success": True,
                "data": page.to_dict(),
                "errors": None,
            }

            return Response(response)
        else:
            response: PageResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_tag_content(request, tag_name):
    """Get all content (blocks and pages) associated with a specific tag"""
    try:
        # Use command to get tag content
        data = {"user": request.user.id, "tag_name": tag_name}
        form = GetTagContentForm(data)

        if not form.is_valid():
            return Response(
                {"success": False, "errors": form.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = GetTagContentCommand(form)
        result = command.execute()

        if not result:
            return Response(
                {"success": False, "errors": {"tag": ["Tag not found"]}},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Format the response data
        direct_blocks_data = []
        for block in result["direct_blocks"]:
            direct_blocks_data.append(block.to_dict_with_children())

        referenced_blocks_data = []
        for block in result["referenced_blocks"]:
            referenced_blocks_data.append(block.to_dict(include_page_context=True))

        pages_data = []
        for page in result["pages"]:
            pages_data.append(page.to_dict())

        tag_content_data: TagContentData = {
            "tag_page": result["tag_page"].to_dict(),
            "direct_blocks": direct_blocks_data,
            "referenced_blocks": referenced_blocks_data,
            "pages": pages_data,
            "total_blocks": len(direct_blocks_data) + len(referenced_blocks_data),
            "total_pages": len(pages_data),
            "total_content": len(direct_blocks_data)
            + len(referenced_blocks_data)
            + len(pages_data),
        }

        response: GetTagContentResponse = {
            "success": True,
            "data": tag_content_data,
            "errors": None,
        }

        return Response(response)

    except Exception as e:
        response: GetTagContentResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def update_page(request):
    """API endpoint to update page"""
    try:
        data = request.data
        data["user"] = request.user.id
        form = UpdatePageForm(data)

        if form.is_valid():
            command = UpdatePageCommand(form)
            page = command.execute()

            response: PageResponse = {
                "success": True,
                "data": page.to_dict(),
                "errors": None,
            }

            return Response(response)
        else:
            response: PageResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def share_page(request):
    """Set the public share mode for a page. Returns the page with its
    share_token populated so the client can render a copy-link UI.
    """
    try:
        data = request.data.copy()
        data["user"] = request.user.id
        form = SharePageForm(data)

        if form.is_valid():
            command = SharePageCommand(form)
            page = command.execute()

            response: PageResponse = {
                "success": True,
                "data": page.to_dict(),
                "errors": None,
            }
            return Response(response)

        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": form.errors,
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_page_favorited(request):
    """Star or unstar a page for the Favorites section in the left nav."""
    try:
        data = request.data.copy()
        data["user"] = request.user.id
        form = SetPageFavoritedForm(data)

        if form.is_valid():
            command = SetPageFavoritedCommand(form)
            page = command.execute()

            response: PageResponse = {
                "success": True,
                "data": page.to_dict(),
                "errors": None,
            }
            return Response(response)

        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": form.errors,
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: PageResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_favorited_pages(request):
    """Return the user's starred pages for the Favorites left-nav section."""
    try:
        form = GetFavoritedPagesForm({"user": request.user.id})

        if form.is_valid():
            command = GetFavoritedPagesCommand(form)
            pages = command.execute()

            pages_data: PagesData = {
                "pages": [page.to_dict() for page in pages],
                "total_count": len(pages),
                "has_more": False,
            }

            response: PagesResponse = {
                "success": True,
                "data": pages_data,
                "errors": None,
            }
            return Response(response)

        response: PagesResponse = {
            "success": False,
            "data": None,
            "errors": form.errors,
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: PagesResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_page(request):
    """API endpoint to delete page"""
    try:
        data = request.data
        data["user"] = request.user.id
        form = DeletePageForm(data)

        if form.is_valid():
            command = DeletePageCommand(form)
            command.execute()

            response: DeleteResponse = {
                "success": True,
                "data": {"message": "Page deleted successfully"},
                "errors": None,
            }

            return Response(response)
        else:
            response: DeleteResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        response: DeleteResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: DeleteResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_pages(request):
    """API endpoint to get user's pages"""
    try:
        data = request.query_params.copy()
        data["user"] = request.user.id
        form = GetUserPagesForm(data)

        if form.is_valid():
            command = GetUserPagesCommand(form)
            result = command.execute()

            pages_data: PagesData = {
                "pages": [page.to_dict() for page in result["pages"]],
                "total_count": result["total_count"],
                "has_more": result["has_more"],
            }

            response: PagesResponse = {
                "success": True,
                "data": pages_data,
                "errors": None,
            }

            return Response(response)
        else:
            response: PagesResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: PagesResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# New block-centric API endpoints
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_page_with_blocks(request):
    """Get a page with all its blocks"""
    try:
        data = request.query_params.copy()
        data["user"] = request.user.id
        form = GetPageWithBlocksForm(data)

        if form.is_valid():
            command = GetPageWithBlocksCommand(form)
            page, direct_blocks, referenced_blocks, overdue_blocks = command.execute()

            page_with_blocks_data = PageWithBlocksData(
                page=page.to_dict(),
                direct_blocks=[
                    block.to_dict_with_children() for block in direct_blocks
                ],
                referenced_blocks=[
                    block.to_dict(include_page_context=True)
                    for block in referenced_blocks
                ],
                overdue_blocks=[
                    block.to_dict(include_page_context=True) for block in overdue_blocks
                ],
            )

            response: GetPageWithBlocksResponse = {
                "success": True,
                "data": page_with_blocks_data,
                "errors": None,
            }

            return Response(response)
        else:
            response: GetPageWithBlocksResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: GetPageWithBlocksResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_block(request):
    """Create a new block"""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = CreateBlockForm(data)

        if form.is_valid():
            command = CreateBlockCommand(form)
            block = command.execute()

            response: BlockResponse = {
                "success": True,
                "data": block.to_dict(),
                "errors": None,
            }

            return Response(response)
        else:
            response: BlockResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: BlockResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def update_block(request):
    """Update a block"""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = UpdateBlockForm(data)

        if form.is_valid():
            command = UpdateBlockCommand(form)
            block = command.execute()

            response: BlockResponse = {
                "success": True,
                "data": block.to_dict(),
                "errors": None,
            }

            return Response(response)
        else:
            response: BlockResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: BlockResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_block(request):
    """Delete a block"""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = DeleteBlockForm(data)

        if form.is_valid():
            command = DeleteBlockCommand(form)
            command.execute()

            response: DeleteResponse = {
                "success": True,
                "data": {"message": "Block deleted successfully"},
                "errors": None,
            }

            return Response(response)
        else:
            response: DeleteResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        response: DeleteResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: DeleteResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def reorder_blocks(request):
    """Batch reorder blocks in a single request.

    Accepts: {"blocks": [{"uuid": "...", "order": N}, ...]}
    """
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = ReorderBlocksForm(data)

        if form.is_valid():
            command = ReorderBlocksCommand(form)
            command.execute()

            return Response(
                {
                    "success": True,
                    "data": {"message": "Blocks reordered successfully"},
                    "errors": None,
                }
            )
        else:
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schedule_block(request):
    """Set or clear a block's scheduled_for, optionally adding a morning-of
    reminder. See issue #59 phase 4.
    """
    try:
        data = request.data.copy()
        data["user"] = request.user.id
        form = ScheduleBlockForm(data)

        if form.is_valid():
            block = ScheduleBlockCommand(form).execute()
            response: BlockResponse = {
                "success": True,
                "data": block.to_dict(),
                "errors": None,
            }
            return Response(response)

        response: BlockResponse = {
            "success": False,
            "data": None,
            "errors": form.errors,
        }
        return Response(response, status=status.HTTP_400_BAD_REQUEST)
    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        response: BlockResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def toggle_block_todo(request):
    """Toggle a block's todo status"""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = ToggleBlockTodoForm(data)

        if form.is_valid():
            command = ToggleBlockTodoCommand(form)
            block = command.execute()

            response: BlockResponse = {
                "success": True,
                "data": block.to_dict(),
                "errors": None,
            }

            return Response(response)
        else:
            response: BlockResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: BlockResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_historical_data(request):
    """Get historical pages and blocks"""
    try:
        # Create and validate form
        form_data = request.query_params.copy()
        form_data["user"] = request.user.pk
        form = GetHistoricalDataForm(form_data)
        if not form.is_valid():
            response: GetHistoricalDataResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

        # Use command to get historical data
        command = GetHistoricalDataCommand(form=form)
        result: HistoricalData = command.execute()

        response: GetHistoricalDataResponse = {
            "success": True,
            "data": result,
            "errors": None,
        }

        return Response(response)

    except Exception as e:
        response: GetHistoricalDataResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def move_undone_todos(request):
    """Move past undone TODOs to current day or specified date"""
    try:
        form_data = {"user": request.user}

        # Check if target_date is provided in request data
        if hasattr(request, "data") and "target_date" in request.data:
            form_data["target_date"] = request.data["target_date"]

        form = MoveUndoneTodosForm(form_data)

        if not form.is_valid():
            response: MoveUndoneTodosResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        todos_data: MoveUndoneTodosData = {
            "moved_count": result["moved_count"],
            "target_page": result["target_page"],
            "moved_blocks": result["moved_blocks"],
            "message": result["message"],
        }

        response: MoveUndoneTodosResponse = {
            "success": True,
            "data": todos_data,
            "errors": None,
        }

        return Response(response)

    except Exception as e:
        response: MoveUndoneTodosResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def move_block_to_daily(request):
    """Move a single block (and its descendants) to a daily note page."""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = MoveBlockToDailyForm(data)

        if not form.is_valid():
            response: MoveBlockToDailyResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

        command = MoveBlockToDailyCommand(form)
        result = command.execute()

        response: MoveBlockToDailyResponse = {
            "success": True,
            "data": result,
            "errors": None,
        }
        return Response(response)

    except ValidationError as e:
        return Response(
            {"success": False, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: MoveBlockToDailyResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_graph_data(request):
    """Return the user's pages and their connections as a node/edge graph."""
    try:
        data = request.query_params.copy()
        data["user"] = request.user.id
        form = GetGraphDataForm(data)

        if not form.is_valid():
            response: GraphDataResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

        command = GetGraphDataCommand(form)
        result: GraphData = command.execute()

        response: GraphDataResponse = {
            "success": True,
            "data": result,
            "errors": None,
        }
        return Response(response)

    except Exception as e:
        response: GraphDataResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_pages(request):
    """API endpoint to search pages by title and slug"""
    try:
        data = request.query_params.copy()
        data["user"] = request.user.id
        form = SearchPagesForm(data)

        if form.is_valid():
            command = SearchPagesCommand(form)
            result = command.execute()

            search_data: PagesData = {
                "pages": result["pages"],
                "total_count": len(result["pages"]),
                "has_more": False,  # Since we're limiting results, we don't need pagination for search
            }

            response: PagesResponse = {
                "success": True,
                "data": search_data,
                "errors": None,
            }

            return Response(response)
        else:
            response: PagesResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        response: PagesResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_blocks(request):
    """Substring search over block content for the spotlight palette.

    Reuses SearchNotesCommand (same logic the assistant's search_notes
    tool uses) so block search stays consistent across surfaces.
    """
    try:
        data = request.query_params.copy()
        data["user"] = request.user.id
        form = SearchNotesForm(data)

        if form.is_valid():
            result = SearchNotesCommand(form).execute()
            return Response({"success": True, "data": result, "errors": None})

        return Response(
            {"success": False, "data": None, "errors": form.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return Response(
            {
                "success": False,
                "data": None,
                "errors": {"non_field_errors": [str(e)]},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bulk_delete_blocks(request):
    """Delete a list of blocks in a single transaction."""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = BulkDeleteBlocksForm(data)

        if not form.is_valid():
            response: BulkDeleteBlocksResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

        command = BulkDeleteBlocksCommand(form)
        result = command.execute()

        response: BulkDeleteBlocksResponse = {
            "success": True,
            "data": result,
            "errors": None,
        }
        return Response(response)

    except ValidationError as e:
        return Response(
            {"success": False, "data": None, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: BulkDeleteBlocksResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def reminder_action(request, token: str):
    """Public, no-auth handler for a reminder action click from Discord.

    Resolves `token` to a (reminder, action) pair via
    `ConsumeReminderActionCommand`. The command itself is responsible
    for authorizing the click — possession of an unguessable, single-
    use, time-bound token is the credential. The view's only job is
    HTTP shape: return the right status code and render a small
    confirmation page so the user sees something legible after the
    click instead of a JSON blob.

    Status codes mirror the command result:
      - 200: action ran (or block was already complete; no-op)
      - 404: unknown token
      - 410: token expired or already used
    """
    form = ConsumeReminderActionForm({"token": token})
    if not form.is_valid():
        # The URL pattern only matches `<str:token>`, so an invalid form
        # here means the input is too long / malformed — same UX as
        # "unknown token" from the user's POV.
        return render(
            request,
            "knowledge/reminder_action.html",
            {
                "title": "Action link not found",
                "message": "Unknown action link.",
                "block_url": "",
            },
            status=404,
        )

    result = ConsumeReminderActionCommand(form).execute()
    block_url = _block_link_for_result(result)

    status_code = {
        "executed": 200,
        "block_completed": 200,
        "not_found": 404,
        "expired": 410,
        "already_used": 410,
    }.get(result["status"], 400)

    title = {
        "executed": "Done",
        "block_completed": "Already complete",
        "not_found": "Action link not found",
        "expired": "Action link expired",
        "already_used": "Already used",
    }.get(result["status"], "")

    response = render(
        request,
        "knowledge/reminder_action.html",
        {
            "title": title,
            "message": result["detail"],
            "block_url": block_url,
        },
        status=status_code,
    )
    # Action confirmation pages are stateful (they show "executed" /
    # "expired" depending on the click), so don't let an intermediary
    # cache them.
    response["Cache-Control"] = "no-store"
    return response


def _block_link_for_result(result) -> str:
    """Build the in-app block link for the confirmation page, if we can.

    Skips when SITE_URL isn't a real http(s) URL (mirrors the embed's
    `_page_link` behavior) and when the result lacks a block — e.g.
    the token didn't resolve.
    """
    from django.conf import settings

    site_url = settings.SITE_URL or ""
    if not site_url.startswith(("http://", "https://")):
        return ""
    block_uuid = result.get("block_uuid")
    page_slug = result.get("page_slug")
    if not block_uuid or not page_slug:
        return ""
    base = site_url.rstrip("/")
    return f"{base}/knowledge/page/{page_slug}/#block-{block_uuid}"


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bulk_move_blocks(request):
    """Move a list of blocks to a daily note as siblings."""
    try:
        data = request.data.copy()
        data["user"] = request.user.id

        form = BulkMoveBlocksForm(data)

        if not form.is_valid():
            response: BulkMoveBlocksResponse = {
                "success": False,
                "data": None,
                "errors": form.errors,
            }
            return Response(response, status=status.HTTP_400_BAD_REQUEST)

        command = BulkMoveBlocksCommand(form)
        result = command.execute()

        response: BulkMoveBlocksResponse = {
            "success": True,
            "data": result,
            "errors": None,
        }
        return Response(response)

    except ValidationError as e:
        return Response(
            {"success": False, "data": None, "errors": {"non_field_errors": [str(e)]}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception as e:
        response: BulkMoveBlocksResponse = {
            "success": False,
            "data": None,
            "errors": {"non_field_errors": [str(e)]},
        }
        return Response(response, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
