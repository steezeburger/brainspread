from django.core.exceptions import ValidationError
from django.test import TestCase

from knowledge.commands import DuplicatePageCommand
from knowledge.forms import DuplicatePageForm
from knowledge.repositories import BlockRepository

from ..helpers import BlockFactory, PageFactory, UserFactory


class TestDuplicatePageCommand(TestCase):
    """End-to-end tests for issue #106 page duplication / templates.

    DuplicatePageCommand powers three flows: plain Duplicate, Save as
    template, and Use template. These tests pin all three plus the slug
    uniqueness behavior and tree-structure preservation.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory()
        cls.other_user = UserFactory()

    def _make_page_with_tree(self, **page_kwargs):
        """Build a page with a small block tree:

        root_a (todo, content "Buy milk")
          - child_a1 (bullet)
          - child_a2 (bullet)
        root_b (heading)
        """
        page = PageFactory(user=self.user, **page_kwargs)
        root_a = BlockFactory(
            user=self.user,
            page=page,
            content="Buy milk",
            block_type="todo",
            order=1,
        )
        BlockFactory(
            user=self.user,
            page=page,
            parent=root_a,
            content="Whole milk",
            order=1,
        )
        BlockFactory(
            user=self.user,
            page=page,
            parent=root_a,
            content="2%",
            order=2,
        )
        BlockFactory(
            user=self.user,
            page=page,
            content="Section heading",
            block_type="heading",
            order=2,
        )
        return page

    def test_duplicate_creates_copy_suffix_when_no_title_given(self):
        page = PageFactory(user=self.user, title="My Page", slug="my-page")
        form = DuplicatePageForm(
            {"user": self.user.id, "source_page_uuid": str(page.uuid)}
        )
        self.assertTrue(form.is_valid(), form.errors)
        clone = DuplicatePageCommand(form).execute()

        self.assertEqual(clone.title, "My Page (copy)")
        self.assertNotEqual(clone.uuid, page.uuid)
        self.assertEqual(clone.user, self.user)
        # Auto-generated slug from "my page (copy)" should slugify cleanly.
        self.assertTrue(clone.slug.startswith("my-page-copy"))

    def test_duplicate_clones_full_block_tree(self):
        page = self._make_page_with_tree(title="Workout", slug="workout")
        form = DuplicatePageForm(
            {"user": self.user.id, "source_page_uuid": str(page.uuid)}
        )
        self.assertTrue(form.is_valid())
        clone = DuplicatePageCommand(form).execute()

        cloned_blocks = list(BlockRepository.get_page_blocks(clone))
        self.assertEqual(len(cloned_blocks), 4)

        # Root blocks should have no parent and preserve order.
        roots = [b for b in cloned_blocks if b.parent_id is None]
        self.assertEqual(len(roots), 2)
        roots_by_order = sorted(roots, key=lambda b: b.order)
        self.assertEqual(roots_by_order[0].content, "Buy milk")
        self.assertEqual(roots_by_order[0].block_type, "todo")
        self.assertEqual(roots_by_order[1].block_type, "heading")

        # The "Buy milk" root should have its two children cloned and
        # parented to the *clone*, not the original.
        cloned_root_a = roots_by_order[0]
        children = list(BlockRepository.get_child_blocks(cloned_root_a))
        self.assertEqual(len(children), 2)
        self.assertEqual({c.content for c in children}, {"Whole milk", "2%"})
        for child in children:
            self.assertEqual(child.parent_id, cloned_root_a.id)

    def test_duplicate_does_not_share_block_uuids(self):
        page = self._make_page_with_tree(title="Source", slug="source")
        original_uuids = {str(b.uuid) for b in BlockRepository.get_page_blocks(page)}
        form = DuplicatePageForm(
            {"user": self.user.id, "source_page_uuid": str(page.uuid)}
        )
        self.assertTrue(form.is_valid())
        clone = DuplicatePageCommand(form).execute()

        cloned_uuids = {str(b.uuid) for b in BlockRepository.get_page_blocks(clone)}
        self.assertEqual(len(original_uuids & cloned_uuids), 0)

    def test_save_as_template_sets_page_type_template(self):
        page = PageFactory(user=self.user, title="Workout Log", slug="workout-log")
        BlockFactory(user=self.user, page=page, content="warmup")
        form = DuplicatePageForm(
            {
                "user": self.user.id,
                "source_page_uuid": str(page.uuid),
                "new_title": "Workout Log Template",
                "new_page_type": "template",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        clone = DuplicatePageCommand(form).execute()

        self.assertEqual(clone.page_type, "template")
        self.assertEqual(clone.title, "Workout Log Template")
        self.assertEqual(BlockRepository.get_page_blocks(clone).count(), 1)

    def test_use_template_defaults_target_to_page(self):
        # Source is a template; with no override the target should be a
        # regular page (not another template), since the natural use is
        # to instantiate it.
        template = PageFactory(
            user=self.user,
            title="Packing List",
            slug="packing-list-tpl",
            page_type="template",
        )
        BlockFactory(user=self.user, page=template, content="passport")
        form = DuplicatePageForm(
            {
                "user": self.user.id,
                "source_page_uuid": str(template.uuid),
                "new_title": "NYC trip",
            }
        )
        self.assertTrue(form.is_valid())
        clone = DuplicatePageCommand(form).execute()

        self.assertEqual(clone.page_type, "page")
        self.assertEqual(clone.title, "NYC trip")
        self.assertEqual(BlockRepository.get_page_blocks(clone).count(), 1)

    def test_duplicate_daily_normalizes_to_page(self):
        from datetime import date

        daily = PageFactory(
            user=self.user,
            title="2026-04-01",
            slug="2026-04-01",
            page_type="daily",
            date=date(2026, 4, 1),
        )
        BlockFactory(user=self.user, page=daily, content="standup")
        form = DuplicatePageForm(
            {
                "user": self.user.id,
                "source_page_uuid": str(daily.uuid),
                "new_title": "Cloned daily",
            }
        )
        self.assertTrue(form.is_valid())
        clone = DuplicatePageCommand(form).execute()

        # daily → page so we don't end up with two daily pages on the
        # same date (which the daily-page lookup wouldn't tolerate).
        self.assertEqual(clone.page_type, "page")

    def test_duplicate_unique_suffix_when_slug_taken(self):
        page = PageFactory(user=self.user, title="Notes", slug="notes")
        # Manually pre-create a conflicting slug so the unique-suffix path runs.
        PageFactory(user=self.user, title="Notes (copy)", slug="notes-copy")

        form = DuplicatePageForm(
            {"user": self.user.id, "source_page_uuid": str(page.uuid)}
        )
        self.assertTrue(form.is_valid())
        clone = DuplicatePageCommand(form).execute()
        self.assertNotIn(clone.slug, {"notes", "notes-copy"})

    def test_duplicate_rejects_other_users_page(self):
        page = PageFactory(user=self.other_user)
        form = DuplicatePageForm(
            {"user": self.user.id, "source_page_uuid": str(page.uuid)}
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            DuplicatePageCommand(form).execute()

    def test_duplicate_rejects_unknown_uuid(self):
        import uuid as uuid_module

        form = DuplicatePageForm(
            {
                "user": self.user.id,
                "source_page_uuid": str(uuid_module.uuid4()),
            }
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            DuplicatePageCommand(form).execute()

    def test_duplicate_preserves_tag_pages_m2m(self):
        # Tag pages are how blocks reference other pages via #hashtag —
        # cloning a template should keep those references intact.
        tag_page = PageFactory(
            user=self.user, title="#fitness", slug="fitness", page_type="page"
        )
        page = PageFactory(user=self.user, title="Workout", slug="workout-m2m")
        block = BlockFactory(user=self.user, page=page, content="run #fitness")
        block.pages.add(tag_page)

        form = DuplicatePageForm(
            {"user": self.user.id, "source_page_uuid": str(page.uuid)}
        )
        self.assertTrue(form.is_valid())
        clone = DuplicatePageCommand(form).execute()

        cloned_block = BlockRepository.get_page_blocks(clone).first()
        self.assertIsNotNone(cloned_block)
        self.assertIn(tag_page, list(cloned_block.pages.all()))
