from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_alter_user_theme"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="render_emoji",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Whether :shortcode: sequences (e.g. :grimacing:) display "
                    "as emoji. Block content always stores the shortcode text "
                    "itself, so this only affects rendering."
                ),
                verbose_name="render emoji",
            ),
        ),
    ]
