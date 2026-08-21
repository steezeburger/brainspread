from typing import List, TypedDict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.add_template_blocks_to_page_form import AddTemplateBlocksToPageForm
from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block, PageData
from ..repositories import BlockRepository
from ..services.content_tokens import (
    TokenError,
    find_input_tokens,
    resolve_content_tokens,
)
from ..services.token_context import build_token_context
from .sync_block_tags_command import SyncBlockTagsCommand
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

    Apply is the resolve boundary for {{tokens}} (issue #140): they
    stay dormant in the template's own content and resolve here, on the
    cloned copies, against the target page. One resolver context spans
    the whole apply, so {{uuid|name:<label>}} yields the same id in
    every block that mentions the label. Templates containing
    {{input:<label>}} tokens are interactive: when a needed label has
    no value in the form's ``inputs``, nothing is cloned and the result
    carries ``needs_input`` so the client can prompt and re-submit.
    """

    def __init__(self, form: AddTemplateBlocksToPageForm) -> None:
        self.form = form

    def execute(self) -> "AddTemplateBlocksToPageData":
        super().execute()

        user = self.form.cleaned_data["user"]
        template = self.form.cleaned_data["template"]
        target_page = self.form.cleaned_data["target_page"]
        inputs = self.form.cleaned_data.get("inputs") or {}

        needed = self._collect_input_labels(template)
        missing = [label for label in needed if label not in inputs]
        if missing:
            return {
                "added": 0,
                "needs_input": missing,
                "target_page": target_page.to_dict(),
                "template_title": template.title,
                "message": f"{template.title} needs input before it can be applied",
            }

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

            self._resolve_tokens(created, user, target_page, inputs)

        # Touch the target page so it bubbles to the top of Recent.
        # The template itself isn't modified, so we don't touch it.
        touch_form = TouchPageForm(
            data={"user": user.id, "page": str(target_page.uuid)}
        )
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return {
            "added": len(created),
            "needs_input": [],
            "target_page": target_page.to_dict(),
            "template_title": template.title,
            "message": f"Added {len(created)} blocks from {template.title}",
        }

    def _collect_input_labels(self, template) -> List[str]:
        """Every {{input:<label>}} label in the template's blocks, in
        block order, deduplicated."""
        labels: List[str] = []
        for block in BlockRepository.get_page_blocks(template):
            if block.block_type == "code":
                continue
            for label in find_input_tokens(block.content or ""):
                if label not in labels:
                    labels.append(label)
        return labels

    def _resolve_tokens(
        self, created: List[Block], user, target_page, inputs: dict
    ) -> None:
        """Resolve {{tokens}} on the cloned blocks. Shares one context
        across the apply so named uuids wire blocks together; re-syncs
        tags and re-extracts properties on any block whose content
        changed (a resolved value may carry a #tag or a key:: value)."""
        context = build_token_context(user, target_page, inputs=inputs)
        for block in created:
            if not block.content or block.block_type == "code":
                continue
            try:
                resolved = resolve_content_tokens(block.content, context)
            except TokenError as e:
                raise ValidationError(str(e))
            if resolved == block.content:
                continue
            block.content = resolved
            block.save(update_fields=["content"])
            sync_form = SyncBlockTagsForm(
                {
                    "block": block.uuid,
                    "content": block.content,
                    "user": user.id,
                }
            )
            if sync_form.is_valid():
                SyncBlockTagsCommand(sync_form).execute()
            block.extract_properties_from_content()


class AddTemplateBlocksToPageData(TypedDict):
    added: int
    needs_input: List[str]
    target_page: PageData
    template_title: str
    message: str
