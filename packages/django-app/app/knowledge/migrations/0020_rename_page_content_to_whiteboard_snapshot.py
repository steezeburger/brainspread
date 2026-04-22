from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0019_rename_canvas_to_whiteboard"),
    ]

    operations = [
        migrations.RenameField(
            model_name="page",
            old_name="content",
            new_name="whiteboard_snapshot",
        ),
        migrations.AlterField(
            model_name="page",
            name="whiteboard_snapshot",
            field=models.TextField(
                blank=True,
                help_text="Tldraw JSON snapshot for whiteboard pages",
            ),
        ),
    ]
