from typing import List, Optional

from django.db.models import Max, QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import PageEmbeddedView
from ..models.page_embedded_view import SCOPE_DAILY, SCOPE_PAGE


def _is_daily(page) -> bool:
    return getattr(page, "page_type", None) == "daily"


class PageEmbeddedViewRepository(BaseRepository):
    model = PageEmbeddedView

    @classmethod
    def list_for_page(cls, page) -> QuerySet:
        """Embeds to render on ``page``, ordered for display.

        Daily pages return the user's ``scope='daily'`` embeds (which
        are independent of the date being viewed); other pages return
        their own ``scope='page'`` embeds.
        """
        qs = cls.get_queryset().select_related("saved_view")
        if _is_daily(page):
            return qs.filter(user=page.user, scope=SCOPE_DAILY).order_by(
                "order", "created_at"
            )
        return qs.filter(page=page, scope=SCOPE_PAGE).order_by("order", "created_at")

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
        """Look up an existing embed for this (page, saved_view) combo.

        On daily pages we look up by ``(user, saved_view, scope='daily')``
        so that "embed on today" from yesterday's daily still finds the
        existing daily-scoped embed and stays idempotent.
        """
        qs = cls.get_queryset()
        try:
            if _is_daily(page):
                return qs.get(user=page.user, saved_view=saved_view, scope=SCOPE_DAILY)
            return qs.get(page=page, saved_view=saved_view, scope=SCOPE_PAGE)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def next_order_for_page(cls, page) -> int:
        """Order value to use when appending a new embed to ``page``.

        Returns one more than the current max in the relevant scope
        bucket, or 0 if the bucket is empty.
        """
        if _is_daily(page):
            agg = (
                cls.get_queryset()
                .filter(user=page.user, scope=SCOPE_DAILY)
                .aggregate(m=Max("order"))
            )
        else:
            agg = (
                cls.get_queryset()
                .filter(page=page, scope=SCOPE_PAGE)
                .aggregate(m=Max("order"))
            )
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
        scope: str = SCOPE_PAGE,
    ) -> PageEmbeddedView:
        return cls.model.objects.create(
            user=user,
            page=page,
            saved_view=saved_view,
            order=order,
            collapsed=collapsed,
            scope=scope,
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
        """Set ``order`` on each embed of the page's scope bucket to its
        index in ``ordered_uuids``. Embeds whose UUIDs aren't listed
        retain their existing order (defensive — clients can omit
        unknown embeds).
        """
        if _is_daily(page):
            bucket = cls.get_queryset().filter(user=page.user, scope=SCOPE_DAILY)
        else:
            bucket = cls.get_queryset().filter(page=page, scope=SCOPE_PAGE)
        embeds = {str(e.uuid): e for e in bucket}
        for index, raw_uuid in enumerate(ordered_uuids):
            embed = embeds.get(str(raw_uuid))
            if embed is None:
                continue
            if embed.order != index:
                embed.order = index
                embed.save(update_fields=["order", "modified_at"])

    @classmethod
    def clone_to_page(
        cls, source_page, target_page, target_user
    ) -> List[PageEmbeddedView]:
        """Copy every page-scoped embed from ``source_page`` onto
        ``target_page``.

        Used by the template / duplicate-page flow (issue #106) so a
        template's embedded saved views come along when the template
        is instantiated. The saved_view reference is preserved — a
        SavedView is a query, not page-scoped data, so two pages can
        embed the same view independently.

        Daily-scoped embeds are not cloned: they aren't owned by a
        single page and instantiating a template doesn't fork the
        user's daily-page widget set.
        """
        source_embeds = list(
            cls.get_queryset()
            .filter(page=source_page, scope=SCOPE_PAGE)
            .order_by("order", "created_at")
        )
        if not source_embeds:
            return []
        if _is_daily(target_page):
            cloned: List[PageEmbeddedView] = []
            for src in source_embeds:
                existing = (
                    cls.get_queryset()
                    .filter(
                        user=target_user,
                        saved_view=src.saved_view,
                        scope=SCOPE_DAILY,
                    )
                    .first()
                )
                if existing is not None:
                    cloned.append(existing)
                    continue
                cloned.append(
                    cls.model.objects.create(
                        user=target_user,
                        page=None,
                        saved_view=src.saved_view,
                        order=src.order,
                        collapsed=src.collapsed,
                        scope=SCOPE_DAILY,
                    )
                )
            return cloned
        return [
            cls.model.objects.create(
                user=target_user,
                page=target_page,
                saved_view=src.saved_view,
                order=src.order,
                collapsed=src.collapsed,
                scope=SCOPE_PAGE,
            )
            for src in source_embeds
        ]
