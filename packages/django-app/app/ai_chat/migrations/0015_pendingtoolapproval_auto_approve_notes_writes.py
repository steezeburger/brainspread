from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0014_alter_admin_verbose_names"),
    ]

    operations = [
        migrations.AddField(
            model_name="pendingtoolapproval",
            name="auto_approve_notes_writes",
            field=models.BooleanField(default=False),
        ),
    ]
