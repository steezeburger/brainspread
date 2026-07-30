from common.commands.abstract_base_command import AbstractBaseCommand
from core.forms import SubscribePushForm
from core.models.push_subscription import PushSubscription
from core.repositories.push_subscription_repository import PushSubscriptionRepository


class SubscribePushCommand(AbstractBaseCommand):
    """Register (or re-register) a browser's Web Push subscription."""

    def __init__(self, form: SubscribePushForm) -> None:
        self.form = form

    def execute(self) -> PushSubscription:
        super().execute()

        data = self.form.cleaned_data
        return PushSubscriptionRepository.upsert(
            user=data["user"],
            endpoint=data["endpoint"],
            p256dh=data["p256dh"],
            auth=data["auth"],
            user_agent=data.get("user_agent") or "",
        )
