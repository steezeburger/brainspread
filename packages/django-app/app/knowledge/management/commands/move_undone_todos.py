from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core.helpers import today_for_user
from core.models import User
from knowledge.commands import MoveUndoneTodosCommand
from knowledge.forms import MoveUndoneTodosForm


class Command(BaseCommand):
    help = "Move past undone TODOs to current day"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            type=str,
            required=True,
            help="Email of the user to move TODOs for",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_email = options["user"]

        try:
            user = User.objects.get(email=user_email)
        except User.DoesNotExist:
            raise CommandError(f"User with email '{user_email}' does not exist")

        # Create form and command
        form_data = {"user": user, "target_date": today_for_user(user)}
        form = MoveUndoneTodosForm(form_data)

        if not form.is_valid():
            raise CommandError(f"Form validation failed: {form.errors}")

        # Execute command
        command = MoveUndoneTodosCommand(form)
        result = command.execute()

        # Output result
        self.stdout.write(
            self.style.SUCCESS(f"✓ {result['message']} for user {user.email}")
        )

        if result["moved_count"] > 0:
            self.stdout.write(
                f"Target page: {result['target_page']['title']} ({result['target_page']['uuid']})"
            )
