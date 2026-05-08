from typing import List, Optional

from django.db.models import Max, QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import PageEmbeddedView


class PageEmbeddedViewRepository(BaseRepository):
    model = PageEmbeddedView

    @classmethod
    def list_for_page(cls, page) -> QuerySet:
        """Embeds attached to a given page, ordered for display."""
        return (
            cls.get_queryset()
            .filter(page=page)
            .select_related("saved_view")
            .order_by("order", "created_at")
        )

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[PageEmbeddedView]:
        qs = cls.get_queryset()
        if user is not None:
            qs = qs.filter(user=user)
        try:
            return qs.select_related("saved_view", "page").get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_for_page_and_view(cls, page, saved_view) -> Optional[PageEmbeddedView]:
        """Look up the (page, saved_view) embed if it already exists.

        Used by the create command to honor unique_together — the API
        treats a duplicate as "navigate to the existing one" rather
        than raise IntegrityError.
        """
        try:
            return cls.get_queryset().get(page=page, saved_view=saved_view)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def next_order_for_page(cls, page) -> int:
        """Order value to use when appending a new embed to a page.

        Returns one more than the current max, or 0 if the page has no
        embeds yet. Falls back to a stable bottom-of-section default.
        """
        agg = cls.get_queryset().filter(page=page).aggregate(m=Max("order"))
        current_max = agg.get("m")
        return 0 if current_max is None else current_max + 1

    @classmethod
    def create(
        cls,
        *,
        user,
        page,
        saved_view,
        order: int,
        collapsed: bool = False,
    ) -> PageEmbeddedView:
        return cls.model.objects.create(
            user=user,
            page=page,
            saved_view=saved_view,
            order=order,
            collapsed=collapsed,
        )

    @classmethod
    def update(cls, embed: PageEmbeddedView, **fields) -> PageEmbeddedView:
        for k, v in fields.items():
            if not hasattr(embed, k):
                continue
            setattr(embed, k, v)
        embed.save()
        return embed

    @classmethod
    def delete(cls, embed: PageEmbeddedView) -> None:
        embed.delete()

    @classmethod
    def reorder(cls, page, ordered_uuids: List[str]) -> None:
        """Set ``order`` on each embed of the page to its index in
        ``ordered_uuids``. Embeds whose UUIDs aren't listed retain their
        existing order (defensive — clients can omit unknown embeds).
        """
        embeds = {str(e.uuid): e for e in cls.get_queryset().filter(page=page)}
        for index, raw_uuid in enumerate(ordered_uuids):
            embed = embeds.get(str(raw_uuid))
            if embed is None:
                continue
            if embed.order != index:
                embed.order = index
                embed.save(update_fields=["order", "modified_at"])
