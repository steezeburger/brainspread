from django import forms

from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm

from ..repositories import PageRepository


class NormalizeBlockOrderForm(BaseForm):
    """Inputs for the block-order repair: the page, plus an optional
    ``dry_run`` that computes and counts without persisting.

    Deliberately no ``user`` field: the repair is an admin/maintenance
    surface acting across accounts, ownership is derived from the page
    itself, and an active-user filter would make pages owned by a
    deactivated account unrepairable.
    """

    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)
    dry_run = forms.BooleanField(required=False)
