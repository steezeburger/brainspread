from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0021_alter_block_block_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="block",
            name="scheduled_for",
            field=models.DateField(
                blank=True,
                help_text="Daily page this block should surface on (due date)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="block",
            name="completed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the block transitioned to a completed state",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="block",
            index=models.Index(
                fields=["user", "scheduled_for"],
                name="blocks_user_id_e91738_idx",
            ),
        ),
    ]
