from django import forms

from common.forms.base_form import BaseForm

DEFAULT_RETENTION_DAYS = 30


class PurgeExpiredTrashForm(BaseForm):
    """Parameter-less form for the scheduled Trash purge job."""

    retention_days = forms.IntegerField(required=False, min_value=1)
    # DateTimeField accepted here purely for deterministic testing — in
    # production the command uses timezone.now() when this is absent.
    now = forms.DateTimeField(required=False)
