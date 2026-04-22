from django.core.exceptions import ValidationError
from django.utils.text import slugify

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.update_page_form import UpdatePageForm
from ..forms.update_page_references_form import UpdatePageReferencesForm
from ..models import Page
from ..repositories import PageRepository
from .update_page_references_command import UpdatePageReferencesCommand


class UpdatePageCommand(AbstractBaseCommand):
    """Command to update an existing page"""

    def __init__(self, form: UpdatePageForm) -> None:
        self.form = form

    def execute(self) -> Page:
        """Execute the command"""
        super().execute()  # This validates the form

        page = self.form.cleaned_data["page"]

        # Store old values before updating
        old_title = page.title
        old_slug = page.slug

        # Update fields if provided
        title_changed = False

        if (
            "title" in self.form.cleaned_data
            and self.form.cleaned_data["title"] is not None
        ):
            new_title = self.form.cleaned_data["title"]
            if new_title != page.title:
                page.title = new_title
                title_changed = True

                # Always auto-update slug when title changes
                new_slug = slugify(new_title)
                if new_slug != page.slug:
                    # Check if new slug conflicts with existing pages
                    if PageRepository.slug_exists_for_user(
                        slug=new_slug, user=page.user, exclude_page_uuid=str(page.uuid)
                    ):
                        raise ValidationError(
                            f"Page with title '{new_title}' would create a conflicting URL"
                        )

                    page.slug = new_slug

        if (
            "whiteboard_snapshot" in self.form.cleaned_data
            and self.form.cleaned_data["whiteboard_snapshot"] is not None
        ):
            page.whiteboard_snapshot = self.form.cleaned_data["whiteboard_snapshot"]

        if (
            "is_published" in self.form.cleaned_data
            and self.form.cleaned_data["is_published"] is not None
        ):
            page.is_published = self.form.cleaned_data["is_published"]

        page.save()

        # Update references if title changed (which means slug also changed)
        if title_changed:
            self._update_page_references(page, old_title, old_slug)

        return page

    def _update_page_references(
        self, page: Page, old_title: str, old_slug: str
    ) -> None:
        """Update all references to this page when title or slug changes"""
        reference_form_data = {
            "page": str(page.uuid),
            "user": page.user.id,
        }

        # Only include old values that actually changed
        if old_title != page.title:
            reference_form_data["old_title"] = old_title

        if old_slug != page.slug:
            reference_form_data["old_slug"] = old_slug

        reference_form = UpdatePageReferencesForm(data=reference_form_data)
        if reference_form.is_valid():
            reference_command = UpdatePageReferencesCommand(reference_form)
            reference_command.execute()
