from django.core.exceptions import ValidationError

from common.commands.abstract_base_command import AbstractBaseCommand

from ..forms.update_page_embedded_view_form import UpdatePageEmbeddedViewForm
from ..models import PageEmbeddedView
from ..repositories import PageEmbeddedViewRepository


class UpdatePageEmbeddedViewCommand(AbstractBaseCommand):
    """Mutate per-embed UI state — collapsed flag and/or display order.

    Both fields are optional; the caller passes whichever they're
    changing. Order changes from a single-embed update are useful for
    move-up / move-down keyboard nudges; bulk reorder uses the dedicated
    ReorderPageEmbeddedViewsCommand.
    """

    def __init__(self, form: UpdatePageEmbeddedViewForm) -> None:
        self.form = form

    def execute(self) -> PageEmbeddedView:
        super().execute()

        user = self.form.cleaned_data["user"]
        embed_uuid = str(self.form.cleaned_data["embed_uuid"])

        embed = PageEmbeddedViewRepository.get_by_uuid(embed_uuid, user=user)
        if embed is None:
            raise ValidationError("Embed not found")

        fields = {}
        collapsed = self.form.cleaned_data.get("collapsed")
        if collapsed is not None:
            fields["collapsed"] = collapsed
        order = self.form.cleaned_data.get("order")
        if order is not None:
            fields["order"] = order
        # None = color wasn't in the request; "" = explicit clear.
        color = self.form.cleaned_data.get("color")
        if color is not None:
            fields["color"] = color
        if not fields:
            return embed

        return PageEmbeddedViewRepository.update(embed, **fields)
