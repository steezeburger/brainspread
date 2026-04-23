import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_alter_user_theme"),
    ]

    operations = [
        migrations.CreateModel(
            name="Asset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "uuid",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, unique=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("modified_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("snapshot_readable_html", "Snapshot Readable HTML"),
                            ("snapshot_raw_html", "Snapshot Raw HTML"),
                            ("snapshot_screenshot", "Snapshot Screenshot"),
                            ("upload", "User Upload"),
                        ],
                        max_length=40,
                    ),
                ),
                ("file", models.FileField(upload_to="assets/%Y/%m/")),
                ("mime_type", models.CharField(blank=True, max_length=120)),
                ("byte_size", models.PositiveBigIntegerField(default=0)),
                (
                    "sha256",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("source_url", models.URLField(blank=True, max_length=2048)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "assets",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["user", "kind"], name="assets_user_id_kind_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(fields=["sha256"], name="assets_sha256_idx"),
        ),
    ]
