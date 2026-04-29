from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_user_time_format"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="discord_user_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Optional Discord user ID (numeric snowflake) — when set, "
                    "reminder messages mention this user so they get a "
                    "push/desktop notification"
                ),
                max_length=32,
                verbose_name="discord user id",
            ),
        ),
    ]
