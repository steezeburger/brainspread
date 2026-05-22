from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0034_page_embedded_view_daily_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reminderaction",
            name="action",
            field=models.CharField(
                choices=[
                    ("complete", "Mark complete"),
                    ("mark_doing", "Mark doing"),
                    ("snooze_1h", "Snooze 1 hour"),
                    ("snooze_1d", "Snooze 1 day"),
                ],
                max_length=32,
            ),
        ),
    ]
