from django import forms

from common.forms.user_form import UserForm


class ReorderPageEmbeddedViewsForm(UserForm):
    """Reorder all embeds on a page in one shot.

    ``ordered_uuids`` is the desired display order. The repository walks
    it and assigns ``order = index``; embeds not in the list keep their
    existing position (defensive — clients can omit unknowns).
    """

    page_uuid = forms.UUIDField()
    ordered_uuids = forms.JSONField()

    def clean_ordered_uuids(self):
        value = self.cleaned_data.get("ordered_uuids")
        if not isinstance(value, list):
            raise forms.ValidationError("ordered_uuids must be a list of UUID strings")
        for raw in value:
            if not isinstance(raw, str):
                raise forms.ValidationError("ordered_uuids must contain strings")
        return value
