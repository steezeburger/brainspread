import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0045_pageembeddedview_color"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AutomationRun",
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("modified_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "automation_block_uuid",
                    models.UUIDField(
                        db_index=True,
                        help_text="UUID of the #automation block that defined this run",
                    ),
                ),
                (
                    "trigger",
                    models.CharField(
                        choices=[
                            ("schedule", "Schedule"),
                            ("manual", "Manual"),
                            ("event", "Event"),
                            ("webhook", "Webhook"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_error",
                    models.TextField(
                        blank=True, default="", help_text="Failure detail, if any"
                    ),
                ),
                (
                    "result",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Summary of what the run did (e.g. matched/affected counts)",
                    ),
                ),
                (
                    "trigger_context",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="What fired the run (e.g. triggering block uuid, schedule slot)",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="automation_runs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "automation_runs",
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["automation_block_uuid", "-created_at"],
                        name="automation__automat_d21ac6_idx",
                    ),
                    models.Index(
                        fields=["user", "status"], name="automation__user_id_a6d5b4_idx"
                    ),
                ],
            },
        ),
    ]
