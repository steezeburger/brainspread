import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    # The Asset model originally lived in core/ as migration 0010_asset.
    # When we split it out into the `assets` app, DBs that had already
    # applied the old migration would fail the consistency check because
    # web_archives.0001_initial (already applied) now declares a
    # dependency on assets.0001_initial (never applied).
    #
    # `replaces` tells Django: if core.0010_asset is marked applied,
    # treat this migration as applied too - no CreateModel runs on envs
    # that already have the table, and fresh envs run it normally.
    replaces = [("core", "0010_asset")]

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
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
                            (
                                "web_archive_readable_html",
                                "Web Archive Readable HTML",
                            ),
                            ("web_archive_raw_html", "Web Archive Raw HTML"),
                            ("web_archive_screenshot", "Web Archive Screenshot"),
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
