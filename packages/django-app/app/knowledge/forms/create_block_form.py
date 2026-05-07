from typing import Optional

from django import forms
from django.core.exceptions import ValidationError

from assets.models import Asset
from assets.repositories import AssetRepository
from common.forms import UUIDModelChoiceField
from common.forms.base_form import BaseForm
from core.models import User
from core.repositories import UserRepository

from ..models import Block, Page, SavedView
from ..repositories import BlockRepository, PageRepository, SavedViewRepository


class CreateBlockForm(BaseForm):
    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())
    page = UUIDModelChoiceField(queryset=PageRepository.get_queryset())
    content = forms.CharField(required=False, initial="")
    content_type = forms.CharField(max_length=50, required=False, initial="text")
    block_type = forms.CharField(max_length=50, required=False, initial="bullet")
    order = forms.IntegerField(min_value=0, required=False, initial=0)
    parent = UUIDModelChoiceField(
        queryset=BlockRepository.get_queryset(), required=False
    )
    media_url = forms.URLField(required=False, initial="")
    media_metadata = forms.JSONField(required=False, initial=dict)
    properties = forms.JSONField(required=False, initial=dict)
    asset = UUIDModelChoiceField(
        queryset=AssetRepository.get_queryset(), required=False
    )
    # When block_type='query', the SavedView the block embeds.
    query_view = UUIDModelChoiceField(
        queryset=SavedViewRepository.get_queryset(), required=False
    )

    def clean_page(self) -> Optional[Page]:
        page = self.cleaned_data.get("page")
        user = self.cleaned_data.get("user")

        if page and user and page.user != user:
            raise ValidationError("Page does not belong to the specified user")

        return page

    def clean_parent(self) -> Optional[Block]:
        user = self.cleaned_data.get("user")
        parent = None
        if "parent" in self.cleaned_data:
            parent = self.cleaned_data.get("parent")

        if parent and user and parent.user != user:
            raise ValidationError("Parent block does not belong to the specified user")

        return parent

    def clean_user(self) -> User:
        user = self.cleaned_data.get("user")
        if not user:
            raise ValidationError("User is required")
        return user

    def clean_asset(self) -> Optional[Asset]:
        asset = self.cleaned_data.get("asset")
        user = self.cleaned_data.get("user")
        # Caller can only attach their own assets - prevents cross-user
        # asset references via uuid guessing.
        if asset and user and asset.user_id != user.id:
            raise ValidationError("Asset not found")
        return asset

    def clean_query_view(self) -> Optional[SavedView]:
        view = self.cleaned_data.get("query_view")
        user = self.cleaned_data.get("user")
        # Same cross-user guard as `asset` — a uuid alone shouldn't
        # let the caller bind to another user's saved view.
        if view and user and view.user_id != user.id:
            raise ValidationError("Saved view not found")
        return view
