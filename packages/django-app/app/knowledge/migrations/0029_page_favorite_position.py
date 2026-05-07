# Generated for issue #120: reorder favorited pages

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0028_reminderaction"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="favorite_position",
            field=models.IntegerField(
                default=0,
                help_text=(
                    "Order within the user's Favorites list. Lower values "
                    "appear first; ties fall back to title."
                ),
            ),
        ),
    ]
