from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_block_revisions_form import ListBlockRevisionsForm
from ..models import BlockRevisionData
from ..repositories import BlockRevisionRepository


class ListBlockRevisionsCommand(AbstractBaseCommand):
    """List a block's revision history, newest first."""

    def __init__(self, form: ListBlockRevisionsForm) -> None:
        self.form = form

    def execute(self) -> List[BlockRevisionData]:
        super().execute()

        block = self.form.cleaned_data["block"]

        revisions = BlockRevisionRepository.list_for_block(block)
        return [revision.to_dict() for revision in revisions]
