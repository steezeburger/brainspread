from datetime import date
from typing import Any, Dict, Optional

from django.db.models import Count, Q, QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import Page


class PageRepository(BaseRepository):
    model = Page

    @classmethod
    def get_by_uuid(cls, uuid: str, user=None) -> Optional[Page]:
        """Get page by UUID, optionally filtered by user"""
        queryset = cls.get_queryset()
        if user:
            queryset = queryset.filter(user=user)

        try:
            return queryset.get(uuid=uuid)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_by_slug(cls, slug: str, user=None) -> Optional[Page]:
        """Get page by slug, optionally filtered by user"""
        queryset = cls.get_queryset()
        if user:
            queryset = queryset.filter(user=user)

        try:
            return queryset.get(slug=slug)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_user_pages(
        cls, user, published_only: bool = True, limit: int = 10, offset: int = 0
    ) -> Dict[str, Any]:
        """Get paginated user pages with filtering"""
        queryset = cls.get_queryset().filter(user=user)

        if published_only:
            queryset = queryset.filter(is_published=True)

        total_count = queryset.count()
        pages = list(queryset[offset : offset + limit])

        return {
            "pages": pages,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }

    @classmethod
    def get_daily_note(cls, user, date: date) -> Optional[Page]:
        """Get daily note for specific date"""
        try:
            return cls.get_queryset().get(user=user, page_type="daily", date=date)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_or_create_daily_note(cls, user, date: date) -> tuple[Page, bool]:
        """Get or create daily note for specific date"""
        date_str = date.strftime("%Y-%m-%d")
        page, created = cls.model.objects.get_or_create(
            user=user,
            slug=date_str,
            defaults={"title": date_str, "page_type": "daily", "date": date},
        )
        return page, created

    @classmethod
    def search_by_title(cls, user, query: str) -> QuerySet:
        """Search pages by title"""
        return cls.get_queryset().filter(user=user, title__icontains=query)

    @classmethod
    def get_published_pages(cls, user) -> QuerySet:
        """Get all published pages for user"""
        return cls.get_queryset().filter(user=user, is_published=True)

    @classmethod
    def get_unpublished_pages(cls, user) -> QuerySet:
        """Get all unpublished pages for user"""
        return cls.get_queryset().filter(user=user, is_published=False)

    @classmethod
    def create(cls, data: dict) -> Page:
        """Create a new page"""
        return cls.model.objects.create(**data)

    @classmethod
    def update(cls, *, pk=None, uuid=None, obj: Page = None, data: dict) -> Page:
        """Update a page"""
        if obj:
            page = obj
        elif uuid:
            page = cls.get_by_uuid(uuid)
        else:
            page = cls.get(pk=pk)

        if not page:
            raise cls.model.DoesNotExist("Page not found")

        for field, value in data.items():
            if hasattr(page, field):
                setattr(page, field, value)

        page.save()
        return page

    @classmethod
    def delete_by_uuid(cls, uuid: str, user=None) -> bool:
        """Delete page by UUID"""
        page = cls.get_by_uuid(uuid, user)
        if page:
            page.delete()
            return True
        return False

    @classmethod
    def get_pages_by_date_range(cls, user, start_date, end_date, limit=50) -> QuerySet:
        """Get pages modified within the specified date range"""
        return (
            cls.get_queryset()
            .filter(user=user, modified_at__gte=start_date, modified_at__lte=end_date)
            .order_by("-date", "-modified_at")[:limit]
        )

    @classmethod
    def get_recent_pages(cls, user, limit=7) -> QuerySet:
        """Get the most recently modified pages that have meaningful content.

        Includes pages that have blocks as well as whiteboard pages (whose
        content lives in Page.content as a tldraw snapshot rather than in
        Block rows).
        """
        return (
            cls.get_queryset()
            .filter(user=user)
            .annotate(block_count=Count("blocks"))
            .filter(Q(block_count__gt=0) | Q(page_type="whiteboard"))
            .order_by("-modified_at")[:limit]
        )

    @classmethod
    def get_tag_page(cls, tag_name: str, user) -> Optional[Page]:
        """Get tag page by tag name"""
        try:
            return cls.get_queryset().get(
                title=f"#{tag_name}", page_type="tag", user=user
            )
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def get_all_tag_pages(cls, user) -> QuerySet:
        """Get all tag pages for a user"""
        return cls.get_queryset().filter(user=user, page_type="tag").order_by("title")

    @classmethod
    def slug_exists_for_user(
        cls, slug: str, user, exclude_page_uuid: str = None
    ) -> bool:
        """Check if a slug already exists for a user, optionally excluding a specific page"""
        queryset = cls.get_queryset().filter(user=user, slug=slug)

        if exclude_page_uuid:
            queryset = queryset.exclude(uuid=exclude_page_uuid)

        return queryset.exists()
