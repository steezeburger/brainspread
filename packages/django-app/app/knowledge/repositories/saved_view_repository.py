from typing import List, Optional

from django.db.models import QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import SavedView


class SavedViewRepository(BaseRepository):
    model = SavedView

    @classmethod
    def list_for_user(cls, user) -> QuerySet:
        """All views accessible to ``user`` — their own + bundled system views.

        Today every system view is seeded per-user (see the seed migration),
        so this is just a per-user list. Kept as a separate method to leave
        room for a global system-view scheme later.
        """
        return cls.get_queryset().filter(user=user).order_by("-is_system", "name")

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[SavedView]:
        qs = cls.get_queryset()
        if user is not None:
            qs = qs.filter(user=user)
        try:
            return qs.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_slug(cls, slug: str, user) -> Optional[SavedView]:
        try:
            return cls.get_queryset().get(user=user, slug=slug)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_system_view(cls, slug: str, user) -> Optional[SavedView]:
        """The seeded system view with this slug for the user, or None.

        Used by the daily-page Overdue swap — we look up by slug + flag so
        a user-cloned ``overdue`` (different slug, ``is_system=False``)
        doesn't accidentally satisfy the lookup.
        """
        try:
            return cls.get_queryset().get(user=user, slug=slug, is_system=True)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def slug_taken(cls, user, slug: str, exclude_uuid: Optional[str] = None) -> bool:
        qs = cls.get_queryset().filter(user=user, slug=slug)
        if exclude_uuid:
            qs = qs.exclude(uuid=exclude_uuid)
        return qs.exists()

    @classmethod
    def create(
        cls,
        *,
        user,
        name: str,
        slug: str,
        filter_spec: dict,
        sort: list,
        description: str = "",
        is_system: bool = False,
    ) -> SavedView:
        return cls.model.objects.create(
            user=user,
            name=name,
            slug=slug,
            description=description,
            filter=filter_spec,
            sort=sort,
            is_system=is_system,
        )

    @classmethod
    def update(cls, view: SavedView, **fields) -> SavedView:
        for k, v in fields.items():
            if not hasattr(view, k):
                continue
            setattr(view, k, v)
        view.save()
        return view

    @classmethod
    def delete(cls, view: SavedView) -> None:
        view.delete()

    @classmethod
    def list_system_views_for_user(cls, user) -> List[SavedView]:
        return list(cls.get_queryset().filter(user=user, is_system=True))
