import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0022_block_scheduled_for_completed_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="Reminder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    "modified_at",
                    models.DateTimeField(auto_now=True, db_index=True),
                ),
                (
                    "fire_at",
                    models.DateTimeField(
                        help_text="When this reminder should fire (UTC)"
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("discord_webhook", "Discord Webhook")],
                        default="discord_webhook",
                        max_length=32,
                    ),
                ),
                (
                    "sent_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When this reminder was delivered",
                        null=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "last_error",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Last delivery error, if any",
                    ),
                ),
                (
                    "block",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="reminders",
                        to="knowledge.block",
                    ),
                ),
            ],
            options={
                "db_table": "reminders",
                "ordering": ("fire_at",),
            },
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(
                fields=["status", "fire_at"], name="reminders_status_ed8ec8_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="reminder",
            index=models.Index(
                fields=["block"], name="reminders_block_i_73b3f6_idx"
            ),
        ),
    ]
