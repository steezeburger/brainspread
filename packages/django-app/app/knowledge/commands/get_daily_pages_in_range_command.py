from typing import Any, Dict, List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_daily_pages_in_range_form import GetDailyPagesInRangeForm
from ..models import Block, Page

MAX_RANGE_DAYS = 60


class GetDailyPagesInRangeCommand(AbstractBaseCommand):
    """Fetch the user's daily pages between two dates (inclusive), each
    with its root blocks. Capped at 60 days so the chat tool_result
    payload stays manageable.
    """

    def __init__(self, form: GetDailyPagesInRangeForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        start_date = self.form.cleaned_data["start_date"]
        end_date = self.form.cleaned_data["end_date"]

        if end_date < start_date:
            return {"error": "end_date must be on or after start_date"}
        span_days = (end_date - start_date).days + 1
        if span_days > MAX_RANGE_DAYS:
            return {
                "error": f"range too large ({span_days} days); max {MAX_RANGE_DAYS}"
            }

        pages = list(
            Page.objects.filter(
                user=user,
                page_type="daily",
                date__gte=start_date,
                date__lte=end_date,
            ).order_by("date")
        )
        if not pages:
            return {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "count": 0,
                "results": [],
            }

        page_ids = [p.id for p in pages]
        root_blocks = list(
            Block.objects.filter(page_id__in=page_ids, parent__isnull=True).order_by(
                "page_id", "order"
            )
        )
        blocks_by_page: Dict[int, List[Block]] = {}
        for block in root_blocks:
            blocks_by_page.setdefault(block.page_id, []).append(block)

        results: List[Dict[str, Any]] = []
        for page in pages:
            page_blocks = blocks_by_page.get(page.id, [])
            results.append(
                {
                    "date": page.date.isoformat() if page.date else None,
                    "page_uuid": str(page.uuid),
                    "title": page.title,
                    "slug": page.slug,
                    "root_blocks": [
                        {
                            "block_uuid": str(b.uuid),
                            "block_type": b.block_type,
                            "content": b.content,
                            "order": b.order,
                        }
                        for b in page_blocks
                    ],
                }
            )
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "count": len(results),
            "results": results,
        }
