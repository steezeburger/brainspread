from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_block_type_form import SetBlockTypeForm
from ..forms.toggle_block_todo_form import ToggleBlockTodoForm
from ..models import Block
from .set_block_type_command import SetBlockTypeCommand, get_next_todo_type


class ToggleBlockTodoCommand(AbstractBaseCommand):
    """Command to cycle a block's todo status to the next state."""

    def __init__(self, form: ToggleBlockTodoForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        block: Block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]
        next_type = get_next_todo_type(block.block_type)

        set_form = SetBlockTypeForm(
            {"user": user.id, "block": str(block.uuid), "block_type": next_type}
        )
        if not set_form.is_valid():
            # Shouldn't happen — next_type is always a valid choice and ownership
            # was already enforced on the outer form. Surface it loudly if it does.
            raise AssertionError(f"SetBlockTypeForm invalid: {set_form.errors}")

        return SetBlockTypeCommand(set_form).execute()
