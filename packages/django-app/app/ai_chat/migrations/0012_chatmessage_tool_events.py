from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0011_chatmessage_thinking_and_usage"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="tool_events",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
