from itertools import groupby
from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.normalize_block_order_form import NormalizeBlockOrderForm
from ..repositories import BlockRepository


class NormalizeBlockOrderCommand(AbstractBaseCommand):
    """Renumber every sibling group on a page to a gap-free 0..N-1.

    Duplicate / gapped ``order`` values accumulate from historical
    creation paths (tool creations defaulting to 0, the pre-fix template
    offset) and from the client-side reorder race (issue #176) — and the
    editor's two-value order swap can't self-heal once they exist. This
    is the idempotent repair: within each (page, parent) group, blocks
    sort by (order, created_at, id) and renumber contiguously.

    Mechanics that matter:
    - rows are read with select_for_update inside the transaction, so a
      concurrent user reorder can't be overwritten from a stale snapshot;
    - writes go through BlockRepository.reorder_blocks (one bulk_update
      of ["order"]), so a pure maintenance repair neither bumps
      modified_at — which would flood every recency surface with blocks
      the user never touched — nor issues N UPDATEs;
    - cross-page orphans (parent set but living on another page) are
      left untouched: their sibling group lives on the parent's page,
      and renumbering them here would collide with the parent's real
      children.
    """

    def __init__(self, form: NormalizeBlockOrderForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        page = self.form.cleaned_data["page"]

        with transaction.atomic():
            blocks = BlockRepository.get_page_blocks_for_renumber(page)
            page_block_ids = {b.id for b in blocks}
            changes: List[Dict[str, Any]] = []
            groups = 0
            skipped_orphans = 0
            for parent_id, group in groupby(blocks, key=lambda b: b.parent_id):
                if parent_id is not None and parent_id not in page_block_ids:
                    skipped_orphans += sum(1 for _ in group)
                    continue
                groups += 1
                for index, block in enumerate(group):
                    if block.order != index:
                        changes.append({"uuid": str(block.uuid), "order": index})
            if changes and not BlockRepository.reorder_blocks(changes):
                raise ValidationError("block order repair failed to persist")

        return {
            "page_uuid": str(page.uuid),
            "groups": groups,
            "renumbered": len(changes),
            "skipped_orphans": skipped_orphans,
        }
