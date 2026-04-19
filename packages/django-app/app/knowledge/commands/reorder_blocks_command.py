from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.reorder_blocks_form import ReorderBlocksForm
from ..repositories import BlockRepository


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

        success = BlockRepository.reorder_blocks(normalized, user=user)

        if not success:
            raise ValidationError(
                "Failed to reorder blocks. Some blocks may not exist or "
                "belong to a different user."
            )

        return True
