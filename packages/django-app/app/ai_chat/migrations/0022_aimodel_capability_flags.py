from django.db import migrations, models

# Snapshot of the prefix tuples that used to live in
# ai_chat/services/anthropic_service.py. Frozen here so the backfill
# stays stable even when the service file changes.
THINKING_PREFIXES = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)
ADAPTIVE_THINKING_PREFIXES = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)
EFFORT_PREFIXES = (
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
)


def backfill_capabilities(apps, schema_editor):
    AIModel = apps.get_model("ai_chat", "AIModel")
    for ai_model in AIModel.objects.all():
        ai_model.supports_thinking = ai_model.name.startswith(THINKING_PREFIXES)
        ai_model.supports_adaptive_thinking = ai_model.name.startswith(
            ADAPTIVE_THINKING_PREFIXES
        )
        ai_model.supports_effort = ai_model.name.startswith(EFFORT_PREFIXES)
        ai_model.save(
            update_fields=[
                "supports_thinking",
                "supports_adaptive_thinking",
                "supports_effort",
            ]
        )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0021_chatsession_favorite_position"),
    ]

    operations = [
        migrations.AddField(
            model_name="aimodel",
            name="supports_thinking",
            field=models.BooleanField(
                default=False,
                help_text="Model accepts the `thinking` request parameter (any mode).",
            ),
        ),
        migrations.AddField(
            model_name="aimodel",
            name="supports_adaptive_thinking",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Model accepts `thinking: {type: 'adaptive'}`. Implies "
                    "supports_thinking — Haiku 4.5 has thinking but not adaptive."
                ),
            ),
        ),
        migrations.AddField(
            model_name="aimodel",
            name="supports_effort",
            field=models.BooleanField(
                default=False,
                help_text="Model accepts `output_config.effort` (e.g. 'high').",
            ),
        ),
        migrations.RunPython(backfill_capabilities, reverse_noop),
    ]
