from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.reorder_blocks_form import ReorderBlocksForm
from ..forms.touch_page_form import TouchPageForm
from ..repositories import BlockRepository
from .touch_page_command import TouchPageCommand


class ReorderBlocksCommand(AbstractBaseCommand):
    """Command to batch-reorder blocks in a single operation."""

    def __init__(self, form: ReorderBlocksForm) -> None:
        self.form = form

    def execute(self) -> bool:
        super().execute()

        user = self.form.cleaned_data["user"]
        blocks_order_data = self.form.cleaned_data["blocks"]

        normalized = [
            {"uuid": str(item["uuid"]), "order": item["order"]}
            for item in blocks_order_data
        ]

        # Look up the affected pages before the reorder runs so we can
        # bump their modified_at afterwards. A reorder typically targets a
        # single page, but the form doesn't guarantee that, so we take the
        # set of distinct pages the blocks belong to.
        block_uuids = [item["uuid"] for item in normalized]
        affected_pages = list(
            BlockRepository.get_queryset()
            .filter(user=user, uuid__in=block_uuids)
            .values_list("page__uuid", flat=True)
            .distinct()
        )

        success = BlockRepository.reorder_blocks(normalized, user=user)

        if not success:
            raise ValidationError(
                "Failed to reorder blocks. Some blocks may not exist or "
                "belong to a different user."
            )

        for page_uuid in affected_pages:
            touch_form = TouchPageForm(data={"user": user.id, "page": str(page_uuid)})
            if touch_form.is_valid():
                TouchPageCommand(touch_form).execute()

        return True
