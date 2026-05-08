from django import forms

from common.forms.user_form import UserForm


class CreatePageEmbeddedViewForm(UserForm):
    """Embed a SavedView on a Page.

    The (page, saved_view) pair is unique-together at the DB level —
    the matching command treats a duplicate as "navigate to the
    existing embed" rather than re-create.
    """

    page_uuid = forms.UUIDField()
    saved_view_uuid = forms.UUIDField()
