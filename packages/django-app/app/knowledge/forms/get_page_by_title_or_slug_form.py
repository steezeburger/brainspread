from django import forms

from common.forms.base_form import BaseForm
from core.repositories import UserRepository


class GetPageByTitleOrSlugForm(BaseForm):
    """Inputs for the assistant's get_page_by_title_or_slug tool.

    A single string field — the command tries an exact case-insensitive
    title match first and falls back to a slug match. This matters
    because the assistant often gets the slug form (e.g. from a
    `#food-log` hashtag in user input) but our pages have human titles
    like 'Food Log'.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    query = forms.CharField(min_length=1)
