from django import forms

from common.forms import BaseForm


class RunDueAutomationsForm(BaseForm):
    """Inputs for the scheduler's automation dispatch tick. ``now`` exists
    for tests / manual replays; production ticks leave it unset and the
    command uses the current time."""

    now = forms.DateTimeField(required=False)
