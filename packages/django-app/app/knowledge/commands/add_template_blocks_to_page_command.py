from typing import TypedDict

from django.db import transaction
from django.db.models import Max

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.add_template_blocks_to_page_form import AddTemplateBlocksToPageForm
from ..forms.touch_page_form import TouchPageForm
from ..models import PageData
from ..repositories import BlockRepository
from .touch_page_command import TouchPageCommand


class AddTemplateBlocksToPageCommand(AbstractBaseCommand):
    """Append a template's block tree to an existing target page.

    Copy semantics: cloned blocks are independent — checking off a
    cloned todo doesn't affect the template, and re-running this for
    the same template adds another fresh copy. Lands at the bottom of
    the target's existing block order, preserving the template's
    relative parent/child structure. Block tags and properties carry
    over; completed_at is cleared on clone (a copied todo starts
    uncompleted regardless of the source state).
    """

    def __init__(self, form: AddTemplateBlocksToPageForm) -> None:
        self.form = form

    def execute(self) -> "AddTemplateBlocksToPageData":
        super().execute()

        user = self.form.cleaned_data["user"]
        template = self.form.cleaned_data["template"]
        target_page = self.form.cleaned_data["target_page"]

        with transaction.atomic():
            # Pick an order_offset such that every cloned root lands
            # below every existing block on the target. The offset is
            # added to each source order, so source roots starting at
            # order=1 will land at max+1, max+2, ... which keeps
            # relative ordering identical to the template.
            max_order = (
                BlockRepository.get_queryset()
                .filter(page=target_page)
                .aggregate(max_order=Max("order"))["max_order"]
            )
            max_order = max_order if max_order is not None else 0

            created = BlockRepository.clone_block_tree_to_page(
                source_page=template,
                target_page=target_page,
                target_user=user,
                order_offset=max_order,
            )

        # Touch the target page so it bubbles to the top of Recent.
        # The template itself isn't modified, so we don't touch it.
        touch_form = TouchPageForm(
            data={"user": user.id, "page": str(target_page.uuid)}
        )
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return {
            "added": len(created),
            "target_page": target_page.to_dict(),
            "template_title": template.title,
            "message": f"Added {len(created)} blocks from {template.title}",
        }


class AddTemplateBlocksToPageData(TypedDict):
    added: int
    target_page: PageData
    template_title: str
    message: str
