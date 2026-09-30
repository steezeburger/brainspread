from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.set_block_type_form import SetBlockTypeForm
from ..forms.toggle_block_todo_form import ToggleBlockTodoForm
from ..models import Block
from .set_block_type_command import SetBlockTypeCommand, get_next_todo_type


class BlockTodoToggleConflictError(Exception):
    """Raised when the caller's `expected_from_type` no longer matches the
    block's actual block_type — another session cycled it in between. Carries
    the current server-side block so the API can return it unchanged instead
    of cycling from a state the caller never saw (issue #236)."""

    def __init__(self, block: Block) -> None:
        self.block = block
        super().__init__("Block was toggled by another session")


class ToggleBlockTodoCommand(AbstractBaseCommand):
    """Command to cycle a block's todo status to the next state."""

    def __init__(self, form: ToggleBlockTodoForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        block: Block = self.form.cleaned_data["block"]
        user = self.form.cleaned_data["user"]
        source = self.form.cleaned_data.get("source")

        # Optimistic-concurrency check, mirroring UpdateBlockCommand's
        # expected_content: presence in cleaned_data means the caller opted
        # in (BaseForm.clean prunes unsubmitted keys). Without this, a stale
        # page cycles from whatever the block's REAL current type is rather
        # than the type the user actually saw and clicked.
        if "expected_from_type" in self.form.cleaned_data:
            expected_from_type = self.form.cleaned_data["expected_from_type"]
            if expected_from_type != block.block_type:
                raise BlockTodoToggleConflictError(block)

        next_type = get_next_todo_type(block.block_type)

        set_form = SetBlockTypeForm(
            {
                "user": user.id,
                "block": str(block.uuid),
                "block_type": next_type,
                **({"source": source} if source else {}),
            }
        )
        if not set_form.is_valid():
            # Shouldn't happen — next_type is always a valid choice and ownership
            # was already enforced on the outer form. Surface it loudly if it does.
            raise AssertionError(f"SetBlockTypeForm invalid: {set_form.errors}")

        return SetBlockTypeCommand(set_form).execute()
