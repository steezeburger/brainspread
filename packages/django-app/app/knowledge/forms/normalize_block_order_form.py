from django import forms  # noqa: F401  (kept for form-field extensions)

from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm

from ..models import Page
from ..repositories import PageRepository


class NormalizeBlockOrderForm(BaseForm):
    """Inputs for the block-order repair: just the page.

    Deliberately no ``user`` field: the repair is an admin/maintenance
    surface acting across accounts, ownership is derived from the page
    itself, and an active-user filter would make pages owned by a
    deactivated account unrepairable.
    """

    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)

    def clean_page(self) -> Page:
        return self.cleaned_data.get("page")
