import pytz
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from core.helpers import today_for_user
from knowledge.models import Block, Page

User = get_user_model()


class Command(BaseCommand):
    help = "Seed staging environment with sample blocks for today's daily note"

    def add_arguments(self, parser):
        # The createsuperuser --noinput path leaves the superuser at the
        # User model default of UTC, which flips the seeded daily note to
        # the wrong calendar day for anyone west of UTC. Default to Denver
        # so staging matches the maintainer's local "today".
        parser.add_argument(
            "--timezone",
            dest="user_timezone",
            default="America/Denver",
            help=(
                "Timezone to assign to the superuser before computing 'today'. "
                "Defaults to America/Denver."
            ),
        )

    def handle(self, *args, **options):
        # AIProvider / AIModel are referenced by the chat dropdown the
        # moment a user opens the chat panel; without them the panel
        # has nothing selectable. populate_ai_providers_and_models is
        # idempotent (get_or_create), so running it on every staging
        # deploy keeps things in sync without harm.
        self.stdout.write("Populating AI providers and models...")
        call_command("populate_ai_providers_and_models")

        user = User.objects.filter(is_superuser=True).first()
        if not user:
            self.stdout.write(
                self.style.ERROR("No superuser found. Run createsuperuser first.")
            )
            return

        tz_name = options["user_timezone"]
        try:
            pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            self.stdout.write(
                self.style.ERROR(f"Unknown timezone: {tz_name!r}; aborting.")
            )
            return

        if user.timezone != tz_name:
            user.timezone = tz_name
            user.save(update_fields=["timezone"])

        today = today_for_user(user)
        date_str = today.strftime("%Y-%m-%d")

        with transaction.atomic():
            page, created = Page.objects.get_or_create(
                user=user,
                slug=date_str,
                defaults={
                    "title": date_str,
                    "page_type": "daily",
                    "date": today,
                    "is_published": True,
                },
            )

            if not created and Block.objects.filter(page=page).exists():
                self.stdout.write(
                    self.style.WARNING(f"Page {date_str} already has blocks, skipping.")
                )
                return

            def block(content, order, parent=None, block_type="bullet"):
                return Block.objects.create(
                    user=user,
                    page=page,
                    content=content,
                    block_type=block_type,
                    order=order,
                    parent=parent,
                )

            # Top-level blocks
            focus = block("Today's Focus", order=0, block_type="heading")
            block(
                "Review and test block reordering",
                order=0,
                parent=focus,
                block_type="todo",
            )
            indent_todo = block(
                "Indent and outdent nested blocks",
                order=1,
                parent=focus,
                block_type="todo",
            )
            block("Tab to indent a block", order=0, parent=indent_todo)
            block("Shift+Tab to outdent", order=1, parent=indent_todo)
            block("Double-space also indents on mobile", order=2, parent=indent_todo)
            block(
                "Move blocks up and down with the block menu",
                order=2,
                parent=focus,
                block_type="todo",
            )
            block(
                "Set up staging environment", order=3, parent=focus, block_type="done"
            )

            notes = block("Notes", order=1, block_type="heading")
            block(
                "Block ordering now uses a single batch API call instead of N+1 requests",
                order=0,
                parent=notes,
            )
            perf = block("Performance improvements", order=1, parent=notes)
            block(
                "createBlockAfter and createBlockBefore batch sibling shifts",
                order=0,
                parent=perf,
            )
            block(
                "moveBlockUp and moveBlockDown use one reorder call",
                order=1,
                parent=perf,
            )
            block(
                "outdentBlock sibling shifts are now persisted correctly",
                order=2,
                parent=perf,
            )
            block(
                "There's no way to predict the future except by creating it",
                order=2,
                parent=notes,
                block_type="quote",
            )

            ideas = block("Ideas", order=2, block_type="heading")
            block(
                "Add drag-and-drop block reordering",
                order=0,
                parent=ideas,
                block_type="todo",
            )
            block(
                "Collapsible block sections", order=1, parent=ideas, block_type="todo"
            )
            context = block("Context", order=2, parent=ideas)
            block("Blocks can be nested to any depth", order=0, parent=context)
            block("Each block tracks its parent and order", order=1, parent=context)

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} daily note {date_str} with sample blocks for {user.email}"
            )
        )
