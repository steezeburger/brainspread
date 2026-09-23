from typing import Optional

from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.create_custom_variable_form import CreateCustomVariableForm
from ..models import CustomVariable
from ..repositories import CustomVariableRepository
from ..services.content_tokens import (
    BUILTIN_TOKEN_NAMES,
    CUSTOM_TOKEN_NAME_RE,
    find_custom_token_cycle,
)


def clean_custom_variable_name(
    user, raw_name: str, exclude_uuid: Optional[str] = None
) -> str:
    """Normalize ``raw_name`` (tolerating surrounding ``{{ }}``) and
    reject malformed, built-in, or already-used names."""
    name = raw_name.strip()
    if name.startswith("{{") and name.endswith("}}"):
        name = name[2:-2].strip()
    name = name.lower()
    if not CUSTOM_TOKEN_NAME_RE.match(name):
        raise ValidationError(
            "Variable names must start with a letter and use only "
            "letters, digits, and underscores"
        )
    if name in BUILTIN_TOKEN_NAMES:
        raise ValidationError(f"`{{{{{name}}}}}` is a built-in token")
    if CustomVariableRepository.name_taken(user, name, exclude_uuid=exclude_uuid):
        raise ValidationError(f"You already have a variable named `{name}`")
    return name


def reject_custom_variable_cycle(
    user, name: str, expansion: str, replacing: Optional[str] = None
) -> None:
    """Refuse a save that would make ``name`` reference itself, directly
    or through other variables. ``replacing`` is the variable's previous
    name when it's being renamed."""
    expansions = CustomVariableRepository.expansions_for_user(user)
    if replacing:
        expansions.pop(replacing, None)
    expansions[name] = expansion
    cycle = find_custom_token_cycle(name, expansions)
    if cycle:
        raise ValidationError(f"Variable references itself: {' → '.join(cycle)}")


class CreateCustomVariableCommand(AbstractBaseCommand):
    """Create a user-defined ``{{name}}`` token (issue #228)."""

    def __init__(self, form: CreateCustomVariableForm) -> None:
        self.form = form

    def execute(self) -> CustomVariable:
        super().execute()

        user = self.form.cleaned_data["user"]
        expansion = self.form.cleaned_data["expansion"]
        name = clean_custom_variable_name(user, self.form.cleaned_data["name"])
        reject_custom_variable_cycle(user, name, expansion)

        return CustomVariableRepository.create(
            user=user, name=name, expansion=expansion
        )
