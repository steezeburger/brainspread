from django import forms

from common.forms.user_form import UserForm


class UpdatePageEmbeddedViewForm(UserForm):
    """Toggle an embed's collapsed state or move it to a specific order.

    Both fields are optional so the same endpoint can serve "collapse this"
    and "set this embed's order=2" without two endpoints.
    """

    embed_uuid = forms.UUIDField()
    collapsed = forms.NullBooleanField(required=False)
    order = forms.IntegerField(min_value=0, required=False)
