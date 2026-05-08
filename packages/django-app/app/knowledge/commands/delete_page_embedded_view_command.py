from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.delete_page_embedded_view_form import DeletePageEmbeddedViewForm
from ..repositories import PageEmbeddedViewRepository


class DeletePageEmbeddedViewCommand(AbstractBaseCommand):
    """Remove an embed from its page (does not touch the SavedView)."""

    def __init__(self, form: DeletePageEmbeddedViewForm) -> None:
        self.form = form

    def execute(self) -> None:
        super().execute()

        user = self.form.cleaned_data["user"]
        embed_uuid = str(self.form.cleaned_data["embed_uuid"])

        embed = PageEmbeddedViewRepository.get_by_uuid(embed_uuid, user=user)
        if embed is None:
            raise ValidationError("Embed not found")

        PageEmbeddedViewRepository.delete(embed)
