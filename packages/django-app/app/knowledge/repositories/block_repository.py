from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Max, QuerySet

from common.repositories.base_repository import BaseRepository
from core.helpers import today_for_user

from ..models import Block, Page


class BlockRepository(BaseRepository):
    model = Block

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[Block]:
        """Get block by UUID, optionally filtered by user"""
        queryset = cls.get_queryset()
        if user:
            queryset = queryset.filter(user=user)

        try:
            return queryset.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_page_blocks(cls, page: Page, include_children: bool = True) -> QuerySet:
        """Get blocks for a page"""
        queryset = cls.get_queryset().filter(page=page)

        if not include_children:
            queryset = queryset.filter(parent=None)

        return queryset.order_by("order")

    @classmethod
    def get_root_blocks(cls, page: Page) -> QuerySet:
        """Get top-level blocks (no parent) for a page"""
        return cls.get_queryset().filter(page=page, parent=None).order_by("order")

    @classmethod
    def get_child_blocks(cls, parent_block: Block) -> QuerySet:
        """Get direct children of a block"""
        return cls.get_queryset().filter(parent=parent_block).order_by("order")

    @classmethod
    def get_block_descendants(cls, block: Block) -> List[Block]:
        """Get all descendant blocks recursively"""
        descendants = []
        children = cls.get_child_blocks(block)

        for child in children:
            descendants.append(child)
            descendants.extend(cls.get_block_descendants(child))

        return descendants

    @classmethod
    def get_blocks_by_type(cls, user, block_type: str) -> QuerySet:
        """Get blocks by type for a user"""
        return cls.get_queryset().filter(user=user, block_type=block_type)

    @classmethod
    def get_todo_blocks(cls, user) -> QuerySet:
        """Get all todo blocks for user"""
        return cls.get_blocks_by_type(user, "todo")

    @classmethod
    def get_done_blocks(cls, user) -> QuerySet:
        """Get all done blocks for user"""
        return cls.get_blocks_by_type(user, "done")

    @classmethod
    def search_by_content(cls, user, query: str) -> QuerySet:
        """Search blocks by content"""
        return cls.get_queryset().filter(user=user, content__icontains=query)

    @classmethod
    def get_blocks_with_media(cls, user, content_type: str = None) -> QuerySet:
        """Get blocks that have media content"""
        queryset = cls.get_queryset().filter(user=user)

        if content_type:
            queryset = queryset.filter(content_type=content_type)
        else:
            queryset = queryset.exclude(content_type="text")

        return queryset

    @classmethod
    def get_blocks_with_properties(cls, user, property_key: str = None) -> QuerySet:
        """Get blocks that have properties"""
        queryset = cls.get_queryset().filter(user=user)

        if property_key:
            queryset = queryset.filter(properties__has_key=property_key)
        else:
            queryset = queryset.exclude(properties={})

        return queryset

    @classmethod
    def create(cls, data: dict) -> Block:
        """Create a new block"""
        return cls.model.objects.create(**data)

    @classmethod
    def update(cls, *, pk=None, uuid=None, obj: Block = None, data: dict) -> Block:
        """Update a block"""
        if obj:
            block = obj
        elif uuid:
            block = cls.get_by_uuid(uuid)
        else:
            block = cls.get(pk=pk)

        if not block:
            raise cls.model.DoesNotExist("Block not found")

        for field, value in data.items():
            if hasattr(block, field):
                setattr(block, field, value)

        block.save()
        return block

    @classmethod
    def delete_by_uuid(cls, uuid: str, user=None) -> bool:
        """Delete block by UUID"""
        block = cls.get_by_uuid(uuid, user)
        if block:
            block.delete()
            return True
        return False

    @classmethod
    def get_max_order(cls, page: Page, parent: Block = None) -> int:
        """Get the maximum order value for blocks in a page/parent"""
        queryset = cls.get_queryset().filter(page=page, parent=parent)
        max_order = queryset.aggregate(max_order=Max("order"))["max_order"]
        return max_order if max_order is not None else 0

    @classmethod
    def reorder_blocks(cls, blocks_order_data: List[Dict[str, Any]], user=None) -> bool:
        """Reorder blocks using a single bulk_update (2 queries instead of 2N).

        Args:
            blocks_order_data: List of dicts with 'uuid' and 'order' keys
            user: Optional user to scope block lookup for ownership enforcement
        """
        if not blocks_order_data:
            return True

        try:
            with transaction.atomic():
                order_map = {item["uuid"]: item["order"] for item in blocks_order_data}
                queryset = cls.get_queryset().filter(uuid__in=list(order_map.keys()))
                if user is not None:
                    queryset = queryset.filter(user=user)
                blocks = list(queryset)
                if len(blocks) != len(order_map):
                    return False
                for block in blocks:
                    block.order = order_map[str(block.uuid)]
                Block.objects.bulk_update(blocks, ["order"])
                return True
        except Exception:
            return False

    @classmethod
    def get_blocks_by_date_range(cls, user, start_date, end_date, limit=50) -> QuerySet:
        """Get blocks modified within the specified date range"""
        return (
            cls.get_queryset()
            .filter(user=user, modified_at__gte=start_date, modified_at__lte=end_date)
            .select_related("page")
            .order_by("-modified_at")[:limit]
        )

    @classmethod
    def get_recent_blocks_for_page(cls, page: Page, limit=3) -> QuerySet:
        """Get recent blocks for a specific page"""
        return cls.get_queryset().filter(page=page).order_by("-modified_at")[:limit]

    @classmethod
    def get_undone_todos(cls, user) -> QuerySet:
        """Get undone TODO blocks from daily pages before today"""
        today = today_for_user(user)
        return (
            cls.get_queryset()
            .filter(
                user=user,
                block_type="todo",
                page__page_type="daily",
                page__date__lt=today,
            )
            .select_related("page")
            .order_by("page__date", "order")
        )

    @classmethod
    def move_blocks_to_page(cls, blocks: List[Block], target_page: Page) -> bool:
        """Move blocks to target page and update their order"""
        if not blocks:
            return True

        try:
            with transaction.atomic():
                # Get the current max order for ALL blocks on the target page (not just root blocks)
                queryset = cls.get_queryset().filter(page=target_page)
                max_order = queryset.aggregate(max_order=Max("order"))["max_order"]
                max_order = max_order if max_order is not None else 0

                # Update each block's page and order
                for i, block in enumerate(blocks, start=1):
                    block.page = target_page
                    block.order = max_order + i
                    block.save(update_fields=["page", "order"])

                return True
        except Exception:
            return False
