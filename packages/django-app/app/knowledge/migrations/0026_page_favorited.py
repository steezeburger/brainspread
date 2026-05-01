# Generated for issue #48: favorite pages

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0025_page_sharing"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="favorited",
            field=models.BooleanField(
                default=False,
                help_text="Whether the user has starred this page",
            ),
        ),
    ]
