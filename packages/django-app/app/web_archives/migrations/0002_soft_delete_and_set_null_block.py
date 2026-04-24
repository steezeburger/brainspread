from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0021_alter_block_block_type"),
        ("web_archives", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="webarchive",
            name="deleted_at",
            field=models.DateTimeField(db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="webarchive",
            name="is_active",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text=(
                    "Designates whether this object should be treated as "
                    "active. Unselect this instead of deleting objects."
                ),
                verbose_name="active",
            ),
        ),
        migrations.AlterField(
            model_name="webarchive",
            name="block",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="web_archive",
                to="knowledge.block",
            ),
        ),
    ]
