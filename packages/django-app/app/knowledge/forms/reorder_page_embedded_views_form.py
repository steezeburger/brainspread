from django import forms

from common.forms.user_form import UserForm


class ReorderPageEmbeddedViewsForm(UserForm):
    """Reorder all embeds on a page in one shot.

    ``ordered_uuids`` is the desired display order. The repository walks
    it and assigns ``order = index``; embeds not in the list keep their
    existing position (defensive — clients can omit unknowns).
    """

    page_uuid = forms.UUIDField()
    # Django's JSONField treats ``[]`` as empty under required=True, which
    # would reject the cross-user-rejection path's harmless empty input.
    # Mark the field optional and default to ``[]`` in clean.
    ordered_uuids = forms.JSONField(required=False)

    def clean_ordered_uuids(self):
        value = self.cleaned_data.get("ordered_uuids")
        if value is None:
            return []
        if not isinstance(value, list):
            raise forms.ValidationError("ordered_uuids must be a list of UUID strings")
        for raw in value:
            if not isinstance(raw, str):
                raise forms.ValidationError("ordered_uuids must contain strings")
        return value
