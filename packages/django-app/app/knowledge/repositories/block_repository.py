from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional

from django.db import transaction
from django.db.models import Count, F, Max, Q, QuerySet
from django.db.models.functions import TruncDate

from common.repositories.base_repository import BaseRepository

from ..models import Block, Page


def _start_of_local_day(d: date, user) -> datetime:
    """Aware datetime at midnight of ``d`` in the user's timezone. Used to
    turn date-shaped boundaries into datetime bounds for the (now datetime)
    ``due_at`` field. pytz needs ``localize()`` rather than ``tzinfo=`` to
    pick the right DST offset."""
    return user.tz().localize(datetime.combine(d, time.min))


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
    def get_referenced_blocks(
        cls, page: Page, order_by: Iterable[str] = ()
    ) -> List[Block]:
        """Blocks on *other* pages tagged with ``page`` (its "linked
        references"), with redundant descendants removed.

        A tagged block is dropped when one of its ancestors is also tagged
        with the same page: the references list renders each reference's
        full subtree, so the descendant already shows up nested under that
        ancestor. Surfacing it again as its own top-level entry would just
        duplicate it.

        ``order_by`` is applied to the underlying query (defaults to the
        model's Meta ordering). The ancestor walk fetches intermediate
        (untagged) ancestors in bulk per depth level, so it costs one
        query per level rather than one per block.
        """
        qs = (
            cls.get_queryset()
            .filter(pages=page)
            .exclude(page=page)
            .select_related("user", "page", "asset")
            .prefetch_related("reminders")
        )
        if order_by:
            qs = qs.order_by(*order_by)
        tagged = list(qs)
        if not tagged:
            return []

        tagged_ids = {b.id for b in tagged}

        parent_of: Dict[int, Optional[int]] = {b.id: b.parent_id for b in tagged}
        frontier = {
            b.parent_id
            for b in tagged
            if b.parent_id is not None and b.parent_id not in parent_of
        }
        while frontier:
            rows = list(
                cls.get_queryset()
                .filter(id__in=frontier)
                .values_list("id", "parent_id")
            )
            for block_id, parent_id in rows:
                parent_of[block_id] = parent_id
            frontier = {
                parent_id
                for _block_id, parent_id in rows
                if parent_id is not None and parent_id not in parent_of
            }

        def has_tagged_ancestor(block_id: int) -> bool:
            parent_id = parent_of.get(block_id)
            while parent_id is not None:
                if parent_id in tagged_ids:
                    return True
                parent_id = parent_of.get(parent_id)
            return False

        return [b for b in tagged if not has_tagged_ancestor(b.id)]

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
        """Free-text + tag-aware search over the user's blocks.

        Matches a block when any of these holds:
          - the block's text content ICONTAINS the query (the original
            substring behavior)
          - the block is tagged with a Page whose slug ICONTAINS the
            query (e.g. searching "fruit" picks up blocks tagged
            #fruits via the M2M)
          - the block is tagged with a Page whose title ICONTAINS the
            query (covers tag pages whose title was customized away
            from the slug)

        distinct() because the M2M join can multiply rows when a block
        carries several matching tag pages.
        """
        return (
            cls.get_queryset()
            .filter(user=user)
            .filter(
                Q(content__icontains=query)
                | Q(pages__slug__icontains=query)
                | Q(pages__title__icontains=query)
            )
            .distinct()
        )

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

        Dated blocks (due_at is set) are excluded — they surface on their
        due page via the overdue query instead, keeping the original page
        intact as history.

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
                due_at__isnull=True,
            )
            .select_related("page")
            .order_by("page__date", "order")
        )

    @classmethod
    def get_overdue_blocks(cls, user, today) -> QuerySet:
        """Get overdue blocks for a user as of the given date.

        Predicate per issue #59, by due *date* in the user's timezone:
            due_at < start-of-today (user-local)
            AND block_type IN (todo, doing, later)
            AND completed_at IS NULL
            AND user = request.user

        Both all-day and timed items compare by date — a timed item due
        today (even at 3pm) is "due today", not overdue, until tomorrow.
        """
        return (
            cls.get_queryset()
            .filter(
                user=user,
                due_at__lt=_start_of_local_day(today, user),
                block_type__in=("todo", "doing", "later"),
                completed_at__isnull=True,
            )
            .select_related("page", "user")
            .prefetch_related("reminders")
            .order_by("due_at", "order")
        )

    @classmethod
    def get_scheduled_in_range(
        cls,
        user,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> List[Block]:
        """Blocks due within the inclusive date range, ordered for a
        calendar / upcoming-list view. The date range is widened to
        datetime bounds in the user's timezone since due_at is a datetime
        (``[start 00:00, day-after-end 00:00)``)."""
        return list(
            cls.get_queryset()
            .filter(
                user=user,
                due_at__gte=_start_of_local_day(start_date, user),
                due_at__lt=_start_of_local_day(end_date + timedelta(days=1), user),
            )
            .select_related("page")
            .prefetch_related("reminders")
            .order_by("due_at", "order")[:limit]
        )

    @classmethod
    def get_orphaned_blocks(cls, user=None) -> QuerySet:
        """Blocks whose parent lives on a different page than they do.

        Produced by older move paths that updated `page` without clearing
        `parent` — invisible on the recursive page render (which starts
        from parent=None) but still surfaced by type-based queries.
        Newly-introduced moves are safe; this is a historical-data probe.
        """
        qs = (
            cls.get_queryset()
            .filter(parent__isnull=False)
            .exclude(parent__page_id=F("page_id"))
        )
        if user is not None:
            qs = qs.filter(user=user)
        return qs

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
                due_at__isnull=True,
                completed_at__isnull=True,
                created_at__lt=cutoff_dt,
            )
            .select_related("page")
            .order_by("created_at")[:limit]
        )

    @classmethod
    def _compiled_base_queryset(cls, user, compiled) -> QuerySet:
        """Shared filter/exclude logic for a CompiledQuery, before ordering
        and serialization hints. Used by both ``run_compiled_query`` (which
        adds select_related/ordering) and ``count_compiled_query`` (which
        only needs the row count). Keeping the template-page exclusion in
        one place so the two paths can never drift.
        """
        qs = cls.get_queryset().filter(user=user).filter(compiled.filter_q)
        if not compiled.includes_page_type:
            qs = qs.exclude(page__page_type="template")
        return qs

    @classmethod
    def run_compiled_query(
        cls,
        user,
        compiled,
        limit: Optional[int] = None,
    ) -> QuerySet:
        """Execute a CompiledQuery (from knowledge.services.query_engine) for
        the user. Always scoped to ``user`` — saved views can never reach
        across users. When the spec doesn't supply a sort we fall back to
        ``-created_at`` (newest first) — "what did I add lately" is the
        most useful default for an open-ended block list; the older
        ``due_at, order`` default surfaced undated items at the
        top, which felt random for views like "all #brainspread #bugs".

        Template-page blocks are excluded by default — they're
        scaffolding, not active work, so surfacing them in "Overdue" /
        tag views is almost always noise. A filter that explicitly
        mentions ``page_type`` flips ``compiled.includes_page_type``
        and the exclusion is skipped, putting the spec back in control.
        """
        qs = (
            cls._compiled_base_queryset(user, compiled)
            .select_related("page", "user")
            .prefetch_related("reminders")
        )
        if compiled.order_by:
            qs = qs.order_by(*compiled.order_by)
        else:
            qs = qs.order_by("-created_at")
        if limit is not None:
            qs = qs[:limit]
        return qs

    @classmethod
    def count_compiled_query(
        cls,
        user,
        compiled,
        limit: Optional[int] = None,
    ) -> int:
        """Count the blocks a CompiledQuery matches, without fetching or
        serializing the rows. Used by collapsed saved-view embeds, which
        only need the header count — running the full ``run_compiled_query``
        + ``to_dict`` for a header number is wasteful when a daily page can
        carry many collapsed embeds.

        ``limit`` caps the count (via a sliced subquery) so callers can
        cheaply distinguish "exactly N" from "at least N" for truncation
        badges; pass ``limit + 1`` and compare against ``limit``.
        """
        qs = cls._compiled_base_queryset(user, compiled)
        if limit is not None:
            qs = qs[:limit]
        return qs.count()

    @classmethod
    def clone_block_tree_to_page(
        cls,
        source_page: Page,
        target_page: Page,
        target_user,
        order_offset: int = 0,
    ) -> List[Block]:
        """Deep-copy ``source_page``'s block tree onto ``target_page``.

        Used by the page-template / duplicate / add-from-template flows
        (issue #106). Each cloned block gets a fresh UUID; parent/child
        structure, order, block_type, content, properties, media_url,
        asset, due_at / due_at_has_time, and the M2M tag set are preserved.
        completed_at is intentionally cleared on clone — a duplicated
        todo starts uncompleted even if the source was done.

        ``order_offset`` shifts every cloned block's ``order`` by that
        amount, preserving relative ordering. Defaults to 0 (full
        duplicate, target page assumed empty). Callers appending to an
        existing target should pass ``max(target.order) + 1`` (or
        similar) so cloned roots land after the existing rows.

        Returns the list of newly-created blocks.
        """
        source_blocks = list(
            cls.get_queryset().filter(page=source_page).order_by("parent_id", "order")
        )
        if not source_blocks:
            return []

        with transaction.atomic():
            uuid_map: Dict[Any, Block] = {}
            created: List[Block] = []
            # Two-pass: first create all blocks without parent links so we
            # have new UUIDs for everyone, then wire up parents in a second
            # pass. Source blocks were ordered by parent_id then order, so
            # the M2M copy below stays predictable.
            for src in source_blocks:
                new_block = Block.objects.create(
                    user=target_user,
                    page=target_page,
                    parent=None,
                    content=src.content,
                    content_type=src.content_type,
                    block_type=src.block_type,
                    order=src.order + order_offset,
                    media_url=src.media_url,
                    media_metadata=src.media_metadata,
                    properties=dict(src.properties or {}),
                    asset=src.asset,
                    due_at=src.due_at,
                    due_at_has_time=src.due_at_has_time,
                    collapsed=src.collapsed,
                )
                uuid_map[src.id] = new_block
                created.append(new_block)
                # Preserve tag-page M2M so a cloned block keeps its #tags.
                tag_pages = list(src.pages.all())
                if tag_pages:
                    new_block.pages.set(tag_pages)

            # Wire up parent references now that all clones exist.
            parent_updates = []
            for src in source_blocks:
                if src.parent_id is None:
                    continue
                clone = uuid_map[src.id]
                parent_clone = uuid_map.get(src.parent_id)
                if parent_clone is not None:
                    clone.parent = parent_clone
                    parent_updates.append(clone)
            if parent_updates:
                Block.objects.bulk_update(parent_updates, ["parent"])

            return created

    @classmethod
    def move_blocks_to_page(cls, blocks: List[Block], target_page: Page) -> bool:
        """Move blocks to target page and update their order.

        Blocks whose parent isn't also being moved are promoted to root on
        the target page — leaving parent_id pointing at a block on a
        different page produces an orphan: invisible to the recursive
        page render (which starts from parent=None) but still surfaced by
        type-based custom views. Descendants of moved blocks ride along
        so subtrees stay intact on the target page.
        """
        if not blocks:
            return True

        try:
            with transaction.atomic():
                # Get the current max order for ALL blocks on the target page (not just root blocks)
                queryset = cls.get_queryset().filter(page=target_page)
                max_order = queryset.aggregate(max_order=Max("order"))["max_order"]
                max_order = max_order if max_order is not None else 0

                selected_pks = {b.pk for b in blocks}

                for i, block in enumerate(blocks, start=1):
                    block.page = target_page
                    block.order = max_order + i
                    update_fields = ["page", "order"]
                    if (
                        block.parent_id is not None
                        and block.parent_id not in selected_pks
                    ):
                        block.parent = None
                        update_fields.append("parent")
                    block.save(update_fields=update_fields)

                # Drag descendants of moved blocks onto the target page so
                # the subtree stays intact. Skip blocks already in the
                # moving set — they were handled above.
                seen = set(selected_pks)
                for block in blocks:
                    for descendant in cls.get_block_descendants(block):
                        if descendant.pk in seen:
                            continue
                        seen.add(descendant.pk)
                        descendant.page = target_page
                        descendant.save(update_fields=["page"])

                return True
        except Exception:
            return False
