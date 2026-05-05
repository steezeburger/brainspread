from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.repositories import UserRepository

from ..repositories import PageRepository


class GetBacklinksForm(BaseForm):
    """Inputs for the assistant's get_backlinks tool.

    Identified by `page` — return blocks that link to the page (via
    `[[Page Title]]` content references) or are tagged with it (via the
    Block.pages M2M). Block-targets aren't supported; the natural
    "links to a block" notion is just children, which `get_block_by_id`
    already returns.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset(), required=True)
    limit = forms.IntegerField(min_value=1, max_value=200, required=False, initial=50)

    def clean_page(self):
        page = self.cleaned_data.get("page")
        user = self.cleaned_data.get("user")
        if page and user and page.user_id != user.id:
            raise ValidationError("Page not found")
        return page
