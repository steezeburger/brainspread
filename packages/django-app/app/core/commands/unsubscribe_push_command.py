from common.commands.abstract_base_command import AbstractBaseCommand
from core.forms import UnsubscribePushForm
from core.repositories.push_subscription_repository import PushSubscriptionRepository


class UnsubscribePushCommand(AbstractBaseCommand):
    """Remove one of the user's Web Push subscriptions (e.g. on opt-out)."""

    def __init__(self, form: UnsubscribePushForm) -> None:
        self.form = form

    def execute(self) -> int:
        super().execute()

        data = self.form.cleaned_data
        return PushSubscriptionRepository.delete_for_user_by_endpoint(
            data["user"], data["endpoint"]
        )
