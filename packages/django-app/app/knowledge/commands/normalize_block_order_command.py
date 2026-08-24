from operator import attrgetter
from typing import Any, Dict, List, Optional

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.normalize_block_order_form import NormalizeBlockOrderForm
from ..models import Block
from ..repositories import BlockRepository


class NormalizeBlockOrderCommand(AbstractBaseCommand):
    """Renumber every rendered sibling group anchored on a page to a
    gap-free 0..N-1.

    Duplicate / gapped ``order`` values accumulate from historical
    creation paths (tool creations defaulting to 0, the pre-fix template
    offset) and from the client-side reorder race (issue #176) — and the
    editor's two-value order swap can't self-heal once they exist. This
    is the idempotent repair: blocks sort by (order, created_at, id)
    within their group and renumber contiguously.

    Group membership follows the RENDERER, not the page column: child
    lists are fetched by parent with no page filter, so each on-page
    parent's group includes its cross-page children (legacy orphan
    rows living on other pages) — compacting only the on-page members
    could assign an order an excluded child already holds,
    manufacturing the very collision being repaired. Conversely, an
    on-page block whose parent lives elsewhere belongs to that other
    page's repair and is skipped here.

    Mechanics that matter:
    - rows are read with select_for_update inside the transaction, so a
      concurrent user reorder can't be overwritten by renumbering
      computed from a stale snapshot;
    - writes go through BlockRepository.persist_block_orders (batched
      bulk_update of ["order"]), so a pure maintenance repair neither
      bumps modified_at — which would flood every recency surface with
      blocks the user never touched — nor issues N UPDATEs, and a
      database error propagates instead of collapsing into a bool;
    - ``dry_run`` computes and counts without persisting.
    """

    def __init__(self, form: NormalizeBlockOrderForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        page = self.form.cleaned_data["page"]
        dry_run = bool(self.form.cleaned_data.get("dry_run"))
        sort_key = attrgetter(*BlockRepository.SIBLING_SORT_FIELDS)

        with transaction.atomic():
            page_blocks = BlockRepository.get_page_blocks_for_renumber(page)
            page_block_ids = {b.id for b in page_blocks}
            cross_page_children = (
                BlockRepository.get_cross_page_children_for_renumber(
                    page, page_block_ids
                )
                if page_block_ids
                else []
            )

            sibling_groups: Dict[Optional[int], List[Block]] = {}
            skipped_orphans = 0
            for block in page_blocks:
                if (
                    block.parent_id is not None
                    and block.parent_id not in page_block_ids
                ):
                    skipped_orphans += 1
                    continue
                sibling_groups.setdefault(block.parent_id, []).append(block)
            for block in cross_page_children:
                sibling_groups.setdefault(block.parent_id, []).append(block)

            changed: List[Block] = []
            for members in sibling_groups.values():
                for index, block in enumerate(sorted(members, key=sort_key)):
                    if block.order != index:
                        block.order = index
                        changed.append(block)
            if changed and not dry_run:
                BlockRepository.persist_block_orders(changed)

        return {
            "renumbered": len(changed),
            "skipped_orphans": skipped_orphans,
        }
