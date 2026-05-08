from django import forms

from common.forms.user_form import UserForm


class DeletePageEmbeddedViewForm(UserForm):
    embed_uuid = forms.UUIDField()
