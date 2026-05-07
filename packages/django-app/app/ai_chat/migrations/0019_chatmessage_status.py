# Generated for issue #118: persist streaming state across page reload

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0018_pendingtoolapproval_current_page_uuid"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="status",
            field=models.CharField(
                choices=[
                    ("complete", "Complete"),
                    ("streaming", "Streaming"),
                    ("error", "Error"),
                ],
                db_index=True,
                default="complete",
                help_text=(
                    "Lifecycle of an assistant message. 'streaming' rows are"
                    " in-flight responses that the client may reconnect to via"
                    " the message follow endpoint after a page reload."
                ),
                max_length=20,
            ),
        ),
    ]
