import uuid

from django.db import migrations, models

import knowledge.models.reminder_action


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0027_alter_reminder_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReminderAction",
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
                    "action",
                    models.CharField(
                        choices=[
                            ("complete", "Mark complete"),
                            ("snooze_1h", "Snooze 1 hour"),
                            ("snooze_1d", "Snooze 1 day"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "token",
                    models.CharField(
                        default=knowledge.models.reminder_action._generate_token,
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "used_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When the token was consumed (single-use)",
                        null=True,
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        help_text="After this point the token is rejected",
                    ),
                ),
                (
                    "reminder",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="actions",
                        to="knowledge.reminder",
                    ),
                ),
            ],
            options={
                "db_table": "reminder_actions",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="reminderaction",
            index=models.Index(
                fields=["reminder"], name="reminder_ac_reminde_29870c_idx"
            ),
        ),
    ]
