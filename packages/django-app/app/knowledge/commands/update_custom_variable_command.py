from typing import Any, Dict

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.update_custom_variable_form import UpdateCustomVariableForm
from ..models import CustomVariable
from ..repositories import CustomVariableRepository
from .create_custom_variable_command import (
    clean_custom_variable_name,
    reject_custom_variable_cycle,
)


class UpdateCustomVariableCommand(AbstractBaseCommand):
    """Rename and/or re-point a custom variable. Existing blocks are
    unaffected — tokens are snapshot-resolved at save (issue #140)."""

    def __init__(self, form: UpdateCustomVariableForm) -> None:
        self.form = form

    def execute(self) -> CustomVariable:
        super().execute()

        user = self.form.cleaned_data["user"]
        variable_uuid = str(self.form.cleaned_data["variable_uuid"])

        variable = CustomVariableRepository.get_by_uuid(variable_uuid, user=user)
        if variable is None:
            raise ValidationError("Variable not found")

        updates: Dict[str, Any] = {}
        raw_name = self.form.cleaned_data.get("name")
        if raw_name:
            updates["name"] = clean_custom_variable_name(
                user, raw_name, exclude_uuid=variable_uuid
            )
        expansion = self.form.cleaned_data.get("expansion")
        if expansion:
            updates["expansion"] = expansion

        if not updates:
            return variable

        reject_custom_variable_cycle(
            user,
            updates.get("name", variable.name),
            updates.get("expansion", variable.expansion),
            replacing=variable.name,
        )
        return CustomVariableRepository.update(variable, **updates)
