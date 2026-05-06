from typing import List

from django.core.exceptions import ValidationError
from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.reorder_favorited_pages_form import ReorderFavoritedPagesForm
from ..models import Page
from ..repositories import PageRepository


class ReorderFavoritedPagesCommand(AbstractBaseCommand):
    """Persist a new drag-sorted order for the user's favorited pages.

    The form payload is the desired full ordering of the user's favorites.
    Any starred page the caller forgets to include keeps its old position
    relative to the rest, so a partial payload won't silently demote
    pages.
    """

    def __init__(self, form: ReorderFavoritedPagesForm) -> None:
        self.form = form

    def execute(self) -> List[Page]:
        super().execute()

        user = self.form.cleaned_data["user"]
        ordered_uuids: List[str] = self.form.cleaned_data["page_uuids"]

        favorited_pages = list(
            PageRepository.get_queryset().filter(user=user, favorited=True)
        )
        page_by_uuid = {str(p.uuid): p for p in favorited_pages}

        unknown = [u for u in ordered_uuids if u not in page_by_uuid]
        if unknown:
            raise ValidationError(
                "One or more pages are not in your favorites: "
                + ", ".join(unknown)
            )

        # Apply the requested order first, then append any favorites the
        # caller omitted so we never lose them. The omitted ones keep
        # their existing relative order.
        seen = set(ordered_uuids)
        omitted = [
            p
            for p in sorted(
                favorited_pages, key=lambda p: (p.favorite_position, p.title)
            )
            if str(p.uuid) not in seen
        ]
        new_order = ordered_uuids + [str(p.uuid) for p in omitted]

        with transaction.atomic():
            for index, page_uuid in enumerate(new_order):
                page = page_by_uuid[page_uuid]
                if page.favorite_position == index:
                    continue
                page.favorite_position = index
                page.save(update_fields=["favorite_position"])

        return list(PageRepository.get_favorited(user))
