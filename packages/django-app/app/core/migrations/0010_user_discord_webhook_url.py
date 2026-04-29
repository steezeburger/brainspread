from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_alter_user_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="discord_webhook_url",
            field=models.URLField(
                blank=True,
                default="",
                help_text=(
                    "Optional Discord webhook URL used to deliver reminders "
                    "(see issue #59)"
                ),
                max_length=500,
                verbose_name="discord webhook url",
            ),
        ),
    ]
