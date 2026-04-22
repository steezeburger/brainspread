from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0020_rename_page_content_to_whiteboard_snapshot"),
    ]

    operations = [
        migrations.AlterField(
            model_name="block",
            name="block_type",
            field=models.CharField(
                choices=[
                    ("bullet", "Bullet Point"),
                    ("todo", "Todo"),
                    ("doing", "Doing"),
                    ("done", "Done"),
                    ("later", "Later"),
                    ("wontdo", "Won't Do"),
                    ("heading", "Heading"),
                    ("quote", "Quote"),
                    ("code", "Code Block"),
                    ("divider", "Divider"),
                ],
                default="bullet",
                max_length=20,
            ),
        ),
    ]
