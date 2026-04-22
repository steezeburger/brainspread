from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai_chat", "0010_alter_useraisettings_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="thinking",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="input_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="output_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="cache_creation_input_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="cache_read_input_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
