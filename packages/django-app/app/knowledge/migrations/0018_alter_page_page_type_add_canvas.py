from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0017_alter_block_block_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="page",
            name="page_type",
            field=models.CharField(
                choices=[
                    ("page", "Regular Page"),
                    ("daily", "Daily Note"),
                    ("template", "Template"),
                    ("canvas", "Canvas"),
                ],
                default="page",
                max_length=20,
            ),
        ),
    ]
