from typing import Any, Dict, List, Set

from django.db import transaction

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.bulk_set_block_type_form import BulkSetBlockTypeForm
from ..forms.set_block_type_form import SetBlockTypeForm
from ..repositories import BlockRepository
from .set_block_type_command import SetBlockTypeCommand


class BulkSetBlockTypeCommand(AbstractBaseCommand):
    """Set the same block_type on many blocks in one approval. Wraps
    SetBlockTypeCommand per block so completion_at and content prefix
    handling stays in one place. Failures (missing / wrong-user blocks)
    are reported per-uuid and don't roll back the rest.
    """

    def __init__(self, form: BulkSetBlockTypeForm) -> None:
        self.form = form

    def execute(self) -> Dict[str, Any]:
        super().execute()

        user = self.form.cleaned_data["user"]
        block_uuids: List[str] = self.form.cleaned_data["block_uuids"]
        new_type: str = self.form.cleaned_data["new_type"]

        updated_count = 0
        failed: List[Dict[str, str]] = []
        affected_page_uuids: Set[str] = set()

        with transaction.atomic():
            for block_uuid in block_uuids:
                block = BlockRepository.get_by_uuid(block_uuid, user=user)
                if not block:
                    failed.append({"block_uuid": block_uuid, "reason": "not found"})
                    continue
                inner = SetBlockTypeForm(
                    {
                        "user": user.id,
                        "block": str(block.uuid),
                        "block_type": new_type,
                    }
                )
                if not inner.is_valid():
                    failed.append(
                        {
                            "block_uuid": block_uuid,
                            "reason": _first_form_error(inner),
                        }
                    )
                    continue
                updated = SetBlockTypeCommand(inner).execute()
                updated_count += 1
                if updated.page is not None:
                    affected_page_uuids.add(str(updated.page.uuid))

        return {
            "updated_count": updated_count,
            "failed": failed,
            "new_type": new_type,
            "affected_page_uuids": sorted(affected_page_uuids),
        }


def _first_form_error(form) -> str:
    errors = form.errors
    if not errors:
        return "validation failed"
    first_field, field_errors = next(iter(errors.items()))
    if field_errors:
        return f"{first_field}: {field_errors[0]}"
    return "validation failed"
