from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.duplicate_page_form import DuplicatePageForm
from ..models import Page
from ..repositories import BlockRepository, PageRepository


class DuplicatePageCommand(AbstractBaseCommand):
    """Clone a page into a new page owned by the same user, copying the
    full block tree (issue #106).

    Powers three flows:
      * Duplicate page — caller passes only ``source_page_uuid``; result
        keeps the source's page_type (except daily/template, which
        normalize to ``page`` since duplicating those as the same type
        rarely makes sense).
      * Save as template — caller passes ``new_page_type='template'``.
      * Use template — caller passes a template uuid + a ``new_title``;
        result is a regular ``page``.

    The new slug is unique-suffixed if the auto-slugified title is
    already taken (``-copy``, ``-copy-2``, ...).
    """

    DEFAULT_TARGET_FOR_SOURCE = {
        "daily": "page",
        "template": "page",
    }

    def __init__(self, form: DuplicatePageForm) -> None:
        self.form = form

    def execute(self) -> Page:
        super().execute()

        user = self.form.cleaned_data["user"]
        source_uuid = str(self.form.cleaned_data["source_page_uuid"])
        new_title = self.form.cleaned_data.get("new_title")
        new_page_type = self.form.cleaned_data.get("new_page_type") or None

        source = PageRepository.get_by_uuid(source_uuid, user=user)
        if not source:
            raise ValidationError("Page not found")

        title = new_title or f"{source.title} (copy)"
        page_type = new_page_type or self.DEFAULT_TARGET_FOR_SOURCE.get(
            source.page_type, source.page_type
        )

        with transaction.atomic():
            slug = self._unique_slug(user, slugify(title)[:200] or "page")
            new_page = PageRepository.create(
                {
                    "user": user,
                    "title": title,
                    "slug": slug,
                    "is_published": source.is_published,
                    "page_type": page_type,
                    "whiteboard_snapshot": source.whiteboard_snapshot,
                }
            )

            # Templates and regular pages copy block trees. Whiteboard
            # pages have no Block rows — their content lives in
            # whiteboard_snapshot, copied above.
            if page_type != "whiteboard" and source.page_type != "whiteboard":
                BlockRepository.clone_block_tree_to_page(
                    source_page=source,
                    target_page=new_page,
                    target_user=user,
                )

            return new_page

    @staticmethod
    def _unique_slug(user, base: str) -> str:
        """Pick a slug for the new page that doesn't collide with an
        existing page for the same user. Strategy: try ``<base>``, then
        ``<base>-copy``, then ``<base>-copy-2``, ... matching the saved-
        view duplicate naming scheme."""
        if not PageRepository.slug_exists_for_user(base, user):
            return base
        candidate = f"{base}-copy"
        if not PageRepository.slug_exists_for_user(candidate, user):
            return candidate
        n = 2
        while True:
            candidate = f"{base}-copy-{n}"
            if not PageRepository.slug_exists_for_user(candidate, user):
                return candidate
            n += 1
