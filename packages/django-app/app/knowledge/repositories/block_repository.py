from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from django.db.models import Count, Max, QuerySet
from django.db.models.functions import TruncDate

from common.repositories.base_repository import BaseRepository

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
        return (
            cls.get_queryset()
            .filter(page=page, parent=None)
            .select_related("user")
            .prefetch_related("reminders")
            .order_by("order")
        )

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
        """Get undone TODO blocks from daily pages before today.

        Dated blocks (scheduled_for is set) are excluded — they surface on
        their scheduled page via the overdue query instead, keeping the
        original page intact as history.

        "Today" is resolved against the user's timezone via the shared
        today_for_user helper (added on main).
        """
        today = user.today()
        return (
            cls.get_queryset()
            .filter(
                user=user,
                block_type="todo",
                page__page_type="daily",
                page__date__lt=today,
                scheduled_for__isnull=True,
            )
            .select_related("page")
            .order_by("page__date", "order")
        )

    @classmethod
    def get_overdue_blocks(cls, user, today) -> QuerySet:
        """Get overdue scheduled blocks for a user as of the given date.

        Predicate per issue #59:
            scheduled_for < today
            AND block_type IN (todo, doing, later)
            AND completed_at IS NULL
            AND user = request.user
        """
        return (
            cls.get_queryset()
            .filter(
                user=user,
                scheduled_for__lt=today,
                block_type__in=("todo", "doing", "later"),
                completed_at__isnull=True,
            )
            .select_related("page", "user")
            .prefetch_related("reminders")
            .order_by("scheduled_for", "order")
        )

    @classmethod
    def get_scheduled_in_range(
        cls,
        user,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> List[Block]:
        """Blocks with scheduled_for in the inclusive range, ordered for
        a calendar / upcoming-list view."""
        return list(
            cls.get_queryset()
            .filter(
                user=user,
                scheduled_for__gte=start_date,
                scheduled_for__lte=end_date,
            )
            .select_related("page")
            .prefetch_related("reminders")
            .order_by("scheduled_for", "order")[:limit]
        )

    @classmethod
    def get_root_blocks_for_pages(cls, page_ids: Iterable[int]) -> List[Block]:
        """Root blocks (no parent) across multiple pages, ordered by page
        then order. Used to fetch a span of daily notes' top-level
        bullets in one query."""
        return list(
            cls.get_queryset()
            .filter(page_id__in=list(page_ids), parent__isnull=True)
            .order_by("page_id", "order")
        )

    @classmethod
    def get_completion_counts(
        cls, user, start_dt: datetime, end_dt: datetime
    ) -> Dict[str, int]:
        """Count of blocks per block_type whose completed_at falls in
        [start_dt, end_dt). Returns {block_type: count}."""
        rows = (
            cls.get_queryset()
            .filter(user=user, completed_at__gte=start_dt, completed_at__lt=end_dt)
            .values_list("block_type")
            .annotate(c=Count("id"))
        )
        return {row[0]: int(row[1]) for row in rows}

    @classmethod
    def get_open_counts(
        cls,
        user,
        block_types: Iterable[str],
        start_dt: datetime,
        end_dt: datetime,
    ) -> Dict[str, int]:
        """Count of blocks per block_type that were created in the window
        (typically used for open/in-progress states like todo/doing/later)."""
        rows = (
            cls.get_queryset()
            .filter(
                user=user,
                block_type__in=list(block_types),
                created_at__gte=start_dt,
                created_at__lt=end_dt,
            )
            .values_list("block_type")
            .annotate(c=Count("id"))
        )
        return {row[0]: int(row[1]) for row in rows}

    @classmethod
    def get_done_counts_by_local_day(
        cls, user, start_dt: datetime, end_dt: datetime, tz
    ) -> Dict[date, int]:
        """Per-local-day count of blocks transitioned to `done` in the
        UTC window [start_dt, end_dt). Buckets by the user's tz so
        boundaries match what the user sees in the UI."""
        rows = (
            cls.get_queryset()
            .filter(
                user=user,
                block_type="done",
                completed_at__gte=start_dt,
                completed_at__lt=end_dt,
            )
            .annotate(local_day=TruncDate("completed_at", tzinfo=tz))
            .values("local_day")
            .annotate(c=Count("id"))
        )
        return {row["local_day"]: int(row["c"]) for row in rows if row["local_day"]}

    @classmethod
    def get_journal_active_dates(
        cls, user, start_date: date, end_date: date
    ) -> List[date]:
        """Distinct dates within [start, end] where the user's daily
        page has at least one block (i.e. they journaled that day)."""
        page_ids = list(
            Page.objects.filter(
                user=user,
                page_type="daily",
                date__gte=start_date,
                date__lte=end_date,
            ).values_list("id", flat=True)
        )
        if not page_ids:
            return []
        rows = (
            cls.get_queryset()
            .filter(page_id__in=page_ids)
            .values_list("page__date", flat=True)
            .distinct()
        )
        return [d for d in rows if d is not None]

    @classmethod
    def get_completion_active_dates(
        cls,
        user,
        block_types: Iterable[str],
        start_dt: datetime,
        end_dt: datetime,
        tz,
    ) -> List[date]:
        """Distinct user-local dates within the UTC window where the user
        completed at least one block."""
        rows = (
            cls.get_queryset()
            .filter(
                user=user,
                block_type__in=list(block_types),
                completed_at__gte=start_dt,
                completed_at__lt=end_dt,
            )
            .annotate(local_day=TruncDate("completed_at", tzinfo=tz))
            .values_list("local_day", flat=True)
            .distinct()
        )
        return [d for d in rows if d is not None]

    @classmethod
    def get_recent_blocks(cls, user, limit: int) -> List[Block]:
        """Most-recently-modified blocks across all the user's pages.
        Page-loaded for downstream serialization."""
        return list(
            cls.get_queryset()
            .filter(user=user)
            .select_related("page")
            .order_by("-modified_at")[:limit]
        )

    @classmethod
    def get_tag_pair_rows(cls, user, max_rows: int = 10000) -> List[Dict[str, Any]]:
        """Raw (block_id, page_id) rows from the Block.pages M2M scoped
        to the user, capped to keep pathological cases bounded. The
        co-occurrence math (pairing pages that share a block) is done
        in Python by the caller — see GetTagGraphCommand."""
        through = Block.pages.through
        return list(
            through.objects.filter(block__user=user).values("block_id", "page_id")[
                :max_rows
            ]
        )

    @classmethod
    def get_stale_todos(cls, user, cutoff_dt: datetime, limit: int) -> List[Block]:
        """Open TODO blocks (block_type='todo'), unscheduled, not yet
        completed, created before cutoff_dt. Oldest first."""
        return list(
            cls.get_queryset()
            .filter(
                user=user,
                block_type="todo",
                scheduled_for__isnull=True,
                completed_at__isnull=True,
                created_at__lt=cutoff_dt,
            )
            .select_related("page")
            .order_by("created_at")[:limit]
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
