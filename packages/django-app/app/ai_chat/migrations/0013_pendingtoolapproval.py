import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0012_chatmessage_tool_events"),
    ]

    operations = [
        migrations.CreateModel(
            name="PendingToolApproval",
            fields=[
                (
                    "id",
                    models.AutoField(
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
                ("provider_name", models.CharField(max_length=50)),
                ("system_prompt", models.TextField(blank=True, default="")),
                ("messages_snapshot", models.JSONField(default=list)),
                ("assistant_blocks", models.JSONField(default=list)),
                ("tool_uses", models.JSONField(default=list)),
                ("tool_events", models.JSONField(default=list)),
                ("partial_text", models.TextField(blank=True, default="")),
                ("partial_thinking", models.TextField(blank=True, default="")),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                (
                    "cache_creation_input_tokens",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "cache_read_input_tokens",
                    models.PositiveIntegerField(default=0),
                ),
                ("enable_notes_tools", models.BooleanField(default=False)),
                (
                    "enable_notes_write_tools",
                    models.BooleanField(default=False),
                ),
                ("enable_web_search", models.BooleanField(default=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "ai_model",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="ai_chat.aimodel",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pending_approvals",
                        to="ai_chat.chatsession",
                    ),
                ),
            ],
            options={
                "db_table": "ai_chat_pending_tool_approvals",
                "ordering": ("-created_at",),
            },
        ),
    ]
