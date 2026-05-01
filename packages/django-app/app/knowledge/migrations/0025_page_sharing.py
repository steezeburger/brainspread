# Generated for issue #90: page sharing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0024_block_asset"),
    ]

    operations = [
        migrations.AddField(
            model_name="page",
            name="share_mode",
            field=models.CharField(
                choices=[
                    ("private", "Private"),
                    ("link", "Anyone with the link"),
                    ("public", "Public"),
                ],
                default="private",
                help_text="Public visibility of the page",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="page",
            name="share_token",
            field=models.CharField(
                blank=True,
                help_text="Unguessable token used in public share URLs",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
    ]
