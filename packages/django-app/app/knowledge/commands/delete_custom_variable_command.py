from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.delete_custom_variable_form import DeleteCustomVariableForm
from ..repositories import CustomVariableRepository


class DeleteCustomVariableCommand(AbstractBaseCommand):
    """Delete a custom variable. Blocks that already resolved it keep
    their snapshot text."""

    def __init__(self, form: DeleteCustomVariableForm) -> None:
        self.form = form

    def execute(self) -> None:
        super().execute()

        user = self.form.cleaned_data["user"]
        variable_uuid = str(self.form.cleaned_data["variable_uuid"])

        variable = CustomVariableRepository.get_by_uuid(variable_uuid, user=user)
        if variable is None:
            raise ValidationError("Variable not found")

        CustomVariableRepository.delete(variable)
