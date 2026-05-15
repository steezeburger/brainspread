from django import forms
from django.core.exceptions import ValidationError

from common.forms import BaseForm, UUIDModelChoiceField
from core.models import User
from core.repositories import UserRepository

from ..models import Page
from ..repositories.page_repository import PageRepository


class AddTemplateBlocksToPageForm(BaseForm):
    """Inputs for copying a template's block tree onto an existing page.

    Distinct from DuplicatePageCommand — that one creates a brand-new
    page from a template (or any source). This flow leaves the target
    page in place and appends the template's blocks at the bottom of
    its existing tree. The source must actually be a template; pages
    of other types are rejected so the user can't accidentally clone
    an arbitrary page's blocks via this surface.
    """

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    template = UUIDModelChoiceField(
        queryset=PageRepository.get_queryset(), required=True
    )
    target_page = UUIDModelChoiceField(
        queryset=PageRepository.get_queryset(), required=True
    )

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_template(self) -> Page:
        template = self.cleaned_data.get("template")
        user = self.cleaned_data.get("user")
        if template and user and template.user_id != user.id:
            raise ValidationError("Template not found")
        if template and template.page_type != "template":
            raise ValidationError("Source page is not a template")
        return template

    def clean_target_page(self) -> Page:
        page = self.cleaned_data.get("target_page")
        user = self.cleaned_data.get("user")
        if page and user and page.user_id != user.id:
            raise ValidationError("Target page not found")
        if page and page.page_type == "template":
            # Appending a template onto another template is almost
            # certainly a slip — block the call rather than letting
            # the user accidentally bloat a template with another's
            # contents.
            raise ValidationError("Target page may not be a template")
        return page
