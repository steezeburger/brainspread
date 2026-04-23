import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("core", "0010_asset"),
        ("knowledge", "0021_alter_block_block_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WebArchive",
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
                ("source_url", models.URLField(max_length=2048)),
                ("canonical_url", models.URLField(blank=True, max_length=2048)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("in_progress", "In Progress"),
                            ("ready", "Ready"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("failure_reason", models.TextField(blank=True)),
                ("title", models.CharField(blank=True, max_length=500)),
                ("site_name", models.CharField(blank=True, max_length=200)),
                ("author", models.CharField(blank=True, max_length=200)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("og_image_url", models.URLField(blank=True, max_length=2048)),
                ("favicon_url", models.URLField(blank=True, max_length=2048)),
                ("excerpt", models.TextField(blank=True)),
                (
                    "word_count",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("extracted_text", models.TextField(blank=True)),
                (
                    "text_sha256",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("captured_at", models.DateTimeField(blank=True, null=True)),
                (
                    "block",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="web_archive",
                        to="knowledge.block",
                    ),
                ),
                (
                    "readable_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="+",
                        to="core.asset",
                    ),
                ),
                (
                    "raw_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="+",
                        to="core.asset",
                    ),
                ),
                (
                    "screenshot_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="+",
                        to="core.asset",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="web_archives",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "web_archives",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="webarchive",
            index=models.Index(
                fields=["user", "status"], name="webarchives_user_status_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="webarchive",
            index=models.Index(
                fields=["text_sha256"], name="webarchives_text_sha256_idx"
            ),
        ),
    ]
