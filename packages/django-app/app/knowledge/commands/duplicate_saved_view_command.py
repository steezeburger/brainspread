from django.core.exceptions import ValidationError
from django.utils.text import slugify

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.duplicate_saved_view_form import DuplicateSavedViewForm
from ..models import SavedView
from ..repositories import SavedViewRepository


class DuplicateSavedViewCommand(AbstractBaseCommand):
    """Clone a SavedView (system or user-owned) into a new user-owned
    view the caller can edit. The new slug is unique-suffixed if the
    original slug is already taken (``-copy``, ``-copy-2``, ...)."""

    def __init__(self, form: DuplicateSavedViewForm) -> None:
        self.form = form

    def execute(self) -> SavedView:
        super().execute()

        user = self.form.cleaned_data["user"]
        view_uuid = str(self.form.cleaned_data["view_uuid"])
        new_name = (self.form.cleaned_data.get("new_name") or "").strip()

        original = SavedViewRepository.get_by_uuid(view_uuid, user=user)
        if not original:
            raise ValidationError("Saved view not found")

        name = new_name or f"{original.name} (copy)"
        base_slug = slugify(name)[:200] or f"{original.slug}-copy"
        slug = self._unique_slug(user, base_slug)

        return SavedViewRepository.create(
            user=user,
            name=name,
            slug=slug,
            description=original.description,
            filter_spec=original.filter,
            sort=original.sort,
            is_system=False,
        )

    @staticmethod
    def _unique_slug(user, base: str) -> str:
        if not SavedViewRepository.slug_taken(user=user, slug=base):
            return base
        n = 2
        while True:
            candidate = f"{base}-{n}"
            if not SavedViewRepository.slug_taken(user=user, slug=candidate):
                return candidate
            n += 1
