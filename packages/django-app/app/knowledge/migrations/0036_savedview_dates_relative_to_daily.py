from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0035_reminderaction_mark_doing"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedview",
            name="dates_relative_to_daily",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When True, date tokens (today/yesterday/N days ago) in "
                    "this view's filter resolve against the daily page the "
                    "embed is rendered on, rather than the actual current "
                    "date. No-op when the view is rendered outside a daily "
                    "page context."
                ),
            ),
        ),
    ]
