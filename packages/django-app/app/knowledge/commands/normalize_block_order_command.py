from itertools import groupby
from typing import Any, Dict

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
    are sorted by (order, created_at, id) and renumbered contiguously.
    Only rows whose order actually changes are written.
    """

    def __init__(self, form: NormalizeBlockOrderForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()
        page = self.form.cleaned_data["page"]

        blocks = BlockRepository.get_page_blocks_for_renumber(page)
        renumbered = 0
        groups = 0
        with transaction.atomic():
            for _, group in groupby(blocks, key=lambda b: b.parent_id):
                groups += 1
                for index, block in enumerate(group):
                    if block.order != index:
                        block.order = index
                        block.save(update_fields=["order", "modified_at"])
                        renumbered += 1

        return {
            "page_uuid": str(page.uuid),
            "groups": groups,
            "renumbered": renumbered,
        }
