import itertools
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_tag_graph_form import GetTagGraphForm
from ..repositories import BlockRepository, PageRepository


class GetTagGraphCommand(AbstractBaseCommand):
    """Compute page co-occurrence over the Block.pages M2M.

    For each block tagged with N pages we generate C(N, 2) page pairs;
    the count of times each pair shows up is the "shared block" count.
    Returned ordered by shared_count desc, capped by `min_shared` and
    `limit`.

    Pair-counting happens in Python after fetching the M2M rows — for
    typical brainspread workloads (a few thousand tagged blocks) the
    constant factor is fine and the SQL self-join would obscure the
    clear data flow without saving real time.
    """

    def __init__(self, form: GetTagGraphForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        min_shared: int = self.form.cleaned_data.get("min_shared") or 2
        limit: int = self.form.cleaned_data.get("limit") or 30

        rows = BlockRepository.get_tag_pair_rows(user)
        pages_by_block: Dict[int, List[int]] = defaultdict(list)
        for row in rows:
            pages_by_block[row["block_id"]].append(row["page_id"])

        pair_counts: Counter[Tuple[int, int]] = Counter()
        for page_ids in pages_by_block.values():
            unique_sorted = sorted(set(page_ids))
            for a, b in itertools.combinations(unique_sorted, 2):
                pair_counts[(a, b)] += 1

        ranked = [
            (a, b, count)
            for (a, b), count in pair_counts.items()
            if count >= min_shared
        ]
        ranked.sort(key=lambda t: -t[2])
        top = ranked[:limit]

        # Hydrate page metadata in one query.
        page_ids_in_top = {a for a, _, _ in top} | {b for _, b, _ in top}
        pages = (
            PageRepository.get_queryset()
            .filter(user=user, id__in=page_ids_in_top)
            .in_bulk()
        )

        results: List[Dict[str, Any]] = []
        for a_id, b_id, count in top:
            page_a = pages.get(a_id)
            page_b = pages.get(b_id)
            if page_a is None or page_b is None:
                # M2M row pointed at a page not owned by user (shouldn't
                # happen given the through filter), or a since-deleted
                # page. Skip rather than surface garbage.
                continue
            results.append(
                {
                    "page_a_uuid": str(page_a.uuid),
                    "page_a_title": page_a.title,
                    "page_b_uuid": str(page_b.uuid),
                    "page_b_title": page_b.title,
                    "shared_count": count,
                }
            )

        return {
            "min_shared": min_shared,
            "count": len(results),
            "results": results,
        }
