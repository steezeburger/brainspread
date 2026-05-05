from django import forms

from common.forms import BaseForm


class ConsumeReminderActionForm(BaseForm):
    """Inputs for `ConsumeReminderActionCommand`.

    The token is the only piece of authority the caller needs: it
    resolves to a (reminder, action) pair and proves the holder is
    allowed to run that action on that reminder. `now` is accepted
    purely so tests can pin a deterministic clock — production callers
    leave it absent.
    """

    token = forms.CharField(max_length=64, required=True)
    now = forms.DateTimeField(required=False)
