from typing import List

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.list_custom_variables_form import ListCustomVariablesForm
from ..models import CustomVariable
from ..repositories import CustomVariableRepository


class ListCustomVariablesCommand(AbstractBaseCommand):
    """The user's custom variables, sorted by name."""

    def __init__(self, form: ListCustomVariablesForm) -> None:
        self.form = form

    def execute(self) -> List[CustomVariable]:
        super().execute()
        return list(
            CustomVariableRepository.list_for_user(self.form.cleaned_data["user"])
        )
