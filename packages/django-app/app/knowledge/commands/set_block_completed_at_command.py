import pytz
from django.utils import timezone

from common.commands.abstract_base_command import AbstractBaseCommand
from core.models import User

from ..forms.set_block_completed_at_form import SetBlockCompletedAtForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block
from .touch_page_command import TouchPageCommand


class SetBlockCompletedAtCommand(AbstractBaseCommand):
    """Override a terminal block's completed_at timestamp.

    The form has already verified ownership and that the block is in a
    terminal state (done / wontdo). A naive datetime is interpreted in the
    user's timezone before storage so the stored UTC value matches the
    wall-clock time the user entered.
    """

    def __init__(self, form: SetBlockCompletedAtForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        user: User = self.form.cleaned_data["user"]
        block: Block = self.form.cleaned_data["block"]
        completed_at = self.form.cleaned_data["completed_at"]

        if timezone.is_naive(completed_at):
            completed_at = user.tz().localize(completed_at).astimezone(pytz.UTC)

        block.completed_at = completed_at
        block.save(update_fields=["completed_at", "modified_at"])

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return block
