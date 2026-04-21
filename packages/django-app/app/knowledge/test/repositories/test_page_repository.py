import uuid
from datetime import date

from django.test import TestCase

from knowledge.models import Page
from knowledge.repositories import PageRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestPageRepository(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

    def test_should_create_page(self):
        data = {
            "user": self.user,
            "title": "Test Page",
            "slug": "test-page",
            "content": "Test content",
            "is_published": True,
        }

        page = PageRepository.create(data)

        self.assertEqual(page.title, "Test Page")
        self.assertEqual(page.slug, "test-page")
        self.assertEqual(page.content, "Test content")
        self.assertTrue(page.is_published)
        self.assertEqual(page.user, self.user)

    def test_should_get_page_by_uuid(self):
        page = PageFactory(user=self.user)

        found_page = PageRepository.get_by_uuid(str(page.uuid))

        self.assertEqual(found_page, page)

    def test_should_get_page_by_uuid_filtered_by_user(self):
        page = PageFactory(user=self.user)

        # Should find when correct user
        found_page = PageRepository.get_by_uuid(str(page.uuid), user=self.user)
        self.assertEqual(found_page, page)

        # Should not find when different user
        not_found = PageRepository.get_by_uuid(str(page.uuid), user=self.other_user)
        self.assertIsNone(not_found)

    def test_should_get_page_by_slug(self):
        page = PageFactory(user=self.user, slug="test-page")

        found_page = PageRepository.get_by_slug("test-page", user=self.user)

        self.assertEqual(found_page, page)

    def test_should_return_none_for_nonexistent_page(self):
        # Use a properly formatted UUID
        fake_uuid = str(uuid.uuid4())
        result = PageRepository.get_by_uuid(fake_uuid)
        self.assertIsNone(result)

        result = PageRepository.get_by_slug("non-existent-slug", user=self.user)
        self.assertIsNone(result)

    def test_should_get_user_pages_with_pagination(self):
        # Create test pages
        PageFactory.create_batch(5, user=self.user, is_published=True)

        result = PageRepository.get_user_pages(self.user, limit=3, offset=0)

        self.assertEqual(len(result["pages"]), 3)
        self.assertEqual(result["total_count"], 5)
        self.assertTrue(result["has_more"])

    def test_should_filter_published_pages_only(self):
        # Create published and unpublished pages
        published_page = PageFactory(user=self.user, is_published=True)
        PageFactory(user=self.user, is_published=False)

        result = PageRepository.get_user_pages(self.user, published_only=True)

        self.assertEqual(len(result["pages"]), 1)
        self.assertTrue(result["pages"][0].is_published)

    def test_should_get_all_pages_when_published_only_false(self):
        # Create published and unpublished pages
        PageFactory(user=self.user, is_published=True)
        PageFactory(user=self.user, is_published=False)

        result = PageRepository.get_user_pages(self.user, published_only=False)

        self.assertEqual(len(result["pages"]), 2)

    def test_should_get_daily_note(self):
        today = date.today()
        page = PageFactory(
            user=self.user,
            title=today.strftime("%Y-%m-%d"),
            slug=today.strftime("%Y-%m-%d"),
            page_type="daily",
            date=today,
        )

        found_page = PageRepository.get_daily_note(self.user, today)

        self.assertEqual(found_page, page)

    def test_should_get_or_create_daily_note(self):
        today = date.today()

        # Should create when doesn't exist
        page, created = PageRepository.get_or_create_daily_note(self.user, today)

        self.assertTrue(created)
        self.assertEqual(page.page_type, "daily")
        self.assertEqual(page.date, today)
        self.assertEqual(page.title, today.strftime("%Y-%m-%d"))

    def test_should_search_pages_by_title(self):
        PageFactory(user=self.user, title="Django Tutorial")
        PageFactory(user=self.user, title="Python Guide")

        results = PageRepository.search_by_title(self.user, "Django")

        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().title, "Django Tutorial")

    def test_should_update_page_by_uuid(self):
        page = PageFactory(user=self.user, title="Original Title", slug="original-slug")

        update_data = {"title": "Updated Title", "content": "New content"}
        updated_page = PageRepository.update(uuid=str(page.uuid), data=update_data)

        self.assertEqual(updated_page.title, "Updated Title")
        self.assertEqual(updated_page.content, "New content")
        self.assertEqual(updated_page.slug, "original-slug")  # unchanged

    def test_should_delete_page_by_uuid(self):
        page = PageFactory(user=self.user)

        result = PageRepository.delete_by_uuid(str(page.uuid), user=self.user)

        self.assertTrue(result)
        self.assertFalse(Page.objects.filter(uuid=page.uuid).exists())

    def test_should_not_delete_other_users_page(self):
        page = PageFactory(user=self.user)

        result = PageRepository.delete_by_uuid(str(page.uuid), user=self.other_user)

        self.assertFalse(result)
        self.assertTrue(Page.objects.filter(uuid=page.uuid).exists())

    def test_should_get_published_pages(self):
        PageFactory(user=self.user, is_published=True)
        PageFactory(user=self.user, is_published=False)

        published_pages = PageRepository.get_published_pages(self.user)

        self.assertEqual(published_pages.count(), 1)
        self.assertTrue(published_pages.first().is_published)

    def test_should_get_unpublished_pages(self):
        PageFactory(user=self.user, is_published=True)
        PageFactory(user=self.user, is_published=False)

        unpublished_pages = PageRepository.get_unpublished_pages(self.user)

        self.assertEqual(unpublished_pages.count(), 1)
        self.assertFalse(unpublished_pages.first().is_published)

    def test_get_recent_pages_should_include_canvas_pages_without_blocks(self):
        # Canvas pages have no Block rows — their content lives in Page.content.
        # They should still show up in history alongside pages that have blocks.
        page_with_blocks = PageFactory(user=self.user, title="Has Blocks")
        BlockFactory(user=self.user, page=page_with_blocks)

        canvas_page = PageFactory(user=self.user, title="My Canvas", page_type="canvas")

        empty_regular_page = PageFactory(user=self.user, title="No Blocks Here")

        pages = list(PageRepository.get_recent_pages(self.user))
        uuids = {str(p.uuid) for p in pages}

        self.assertIn(str(page_with_blocks.uuid), uuids)
        self.assertIn(str(canvas_page.uuid), uuids)
        self.assertNotIn(str(empty_regular_page.uuid), uuids)
