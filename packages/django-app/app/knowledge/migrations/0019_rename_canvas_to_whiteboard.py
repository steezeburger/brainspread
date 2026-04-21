from django.db import migrations, models


def rename_canvas_to_whiteboard(apps, schema_editor):
    Page = apps.get_model("knowledge", "Page")
    Page.objects.filter(page_type="canvas").update(page_type="whiteboard")


def rename_whiteboard_to_canvas(apps, schema_editor):
    Page = apps.get_model("knowledge", "Page")
    Page.objects.filter(page_type="whiteboard").update(page_type="canvas")


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0018_alter_page_page_type_add_canvas"),
    ]

    operations = [
        migrations.RunPython(
            rename_canvas_to_whiteboard, reverse_code=rename_whiteboard_to_canvas
        ),
        migrations.AlterField(
            model_name="page",
            name="page_type",
            field=models.CharField(
                choices=[
                    ("page", "Regular Page"),
                    ("daily", "Daily Note"),
                    ("template", "Template"),
                    ("whiteboard", "Whiteboard"),
                ],
                default="page",
                max_length=20,
            ),
        ),
    ]
