from django import forms

from common.forms.base_form import BaseForm


class SendDueRemindersForm(BaseForm):
    """Parameter-less form for the scheduled reminder dispatcher."""

    # DateTimeField accepted here purely for deterministic testing — in
    # production the command uses timezone.now() when this is absent.
    now = forms.DateTimeField(required=False)
