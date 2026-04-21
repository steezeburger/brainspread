from datetime import timedelta
from typing import List, TypedDict

from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.get_historical_data_form import GetHistoricalDataForm
from ..models import BlockData, PageData
from ..repositories.block_repository import BlockRepository
from ..repositories.page_repository import PageRepository


class GetHistoricalDataCommand(AbstractBaseCommand):
    """Command to retrieve historical pages and blocks data"""

    def __init__(self, form: GetHistoricalDataForm):
        self.form = form

    def execute(self) -> "HistoricalData":
        """Execute the command and return historical data"""
        super().execute()

        days_back = self.form.cleaned_data.get("days_back", 30)
        limit = self.form.cleaned_data.get("limit", 50)
        user = self.form.cleaned_data.get("user")

        end_date = timezone.now()
        start_date = end_date - timedelta(days=days_back)

        pages = PageRepository.get_recent_pages(user=user, limit=days_back)

        blocks = BlockRepository.get_blocks_by_date_range(
            user=user, start_date=start_date, end_date=end_date, limit=limit
        )

        pages_data = []
        for page in pages:
            page_data = page.to_dict()
            # Get a few recent blocks from this page
            page_blocks = BlockRepository.get_recent_blocks_for_page(page, 3)
            page_data["recent_blocks"] = [block.to_dict() for block in page_blocks]
            pages_data.append(page_data)

        blocks_data = []
        for block in blocks:
            blocks_data.append(block.to_dict(include_page_context=True))

        return HistoricalData(
            pages=pages_data,
            blocks=blocks_data,
            date_range=DateRangeData(
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                days_back=days_back,
            ),
        )


class DateRangeData(TypedDict):
    start: str
    end: str
    days_back: int


class HistoricalData(TypedDict):
    pages: List[PageData]
    blocks: List[BlockData]
    date_range: DateRangeData
