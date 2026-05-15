from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0032_page_embedded_view"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedview",
            name="pinned",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Pinned views surface in the left-nav for one-click access"
                ),
            ),
        ),
    ]
