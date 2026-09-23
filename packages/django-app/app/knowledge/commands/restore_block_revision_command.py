from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.restore_block_revision_form import RestoreBlockRevisionForm
from ..forms.sync_block_tags_form import SyncBlockTagsForm
from ..forms.touch_page_form import TouchPageForm
from ..models import Block, BlockRevision
from ..repositories import BlockRevisionRepository
from .sync_block_tags_command import SyncBlockTagsCommand
from .touch_page_command import TouchPageCommand


class RestoreBlockRevisionCommand(AbstractBaseCommand):
    """Write a past revision's tracked-field values back onto the live
    block. Goes through the same snapshot / record_if_changed pair every
    other tracked-field write uses, so the restore itself becomes a new
    revision — history stays append-only and a restore can be undone by
    restoring the revision it just superseded.
    """

    def __init__(self, form: RestoreBlockRevisionForm) -> None:
        self.form = form

    def execute(self) -> Block:
        super().execute()

        user = self.form.cleaned_data["user"]
        block: Block = self.form.cleaned_data["block"]
        revision: BlockRevision = self.form.cleaned_data["revision"]

        previous_snapshot = BlockRevisionRepository.snapshot(block)

        block.content = revision.content
        block.block_type = revision.block_type
        block.properties = revision.properties
        block.due_at = revision.due_at
        block.due_at_has_time = revision.due_at_has_time
        block.completed_at = revision.completed_at
        block.save(
            update_fields=[
                "content",
                "block_type",
                "properties",
                "due_at",
                "due_at_has_time",
                "completed_at",
                "modified_at",
            ]
        )

        source = self.form.cleaned_data.get("source") or BlockRevision.SOURCE_USER
        BlockRevisionRepository.record_if_changed(block, previous_snapshot, source)

        # Keep the tag M2M in sync with the restored content, same as any
        # other command that writes block.content.
        if block.content and block.block_type != "code":
            sync_form = SyncBlockTagsForm(
                {"block": block.uuid, "content": block.content, "user": user.id}
            )
            if sync_form.is_valid():
                SyncBlockTagsCommand(sync_form).execute()
                block.refresh_from_db()

        touch_form = TouchPageForm(data={"user": user.id, "page": str(block.page.uuid)})
        if touch_form.is_valid():
            TouchPageCommand(touch_form).execute()

        return block
