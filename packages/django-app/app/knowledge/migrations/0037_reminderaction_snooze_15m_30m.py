from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0036_savedview_dates_relative_to_daily"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reminderaction",
            name="action",
            field=models.CharField(
                choices=[
                    ("complete", "Mark complete"),
                    ("mark_doing", "Mark doing"),
                    ("snooze_15m", "Snooze 15 minutes"),
                    ("snooze_30m", "Snooze 30 minutes"),
                    ("snooze_1h", "Snooze 1 hour"),
                    ("snooze_1d", "Snooze 1 day"),
                ],
                max_length=32,
            ),
        ),
    ]
