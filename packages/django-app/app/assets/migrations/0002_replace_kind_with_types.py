from django.db import migrations, models


# Maps the old `kind` discriminator onto the new (asset_type, file_type)
# pair. Kept module-level so the forward and reverse data migrations stay
# in sync.
KIND_TO_TYPES = {
    "web_archive_readable_html": ("web_archive_readable", "html"),
    "web_archive_raw_html": ("web_archive_raw", "html"),
    "web_archive_screenshot": ("web_archive_screenshot", "image"),
    "upload": ("upload", "other"),
}

# Reverse map for the rollback path. Several (asset_type, file_type) pairs
# only have one sensible old `kind`, but for the file_type=image rows on
# web_archive_raw (PDFs/images captured by the binary path) we have to
# round-trip back to web_archive_raw_html (the old name was a misnomer).
TYPES_TO_KIND = {
    ("web_archive_readable", "html"): "web_archive_readable_html",
    ("web_archive_raw", "html"): "web_archive_raw_html",
    ("web_archive_raw", "pdf"): "web_archive_raw_html",
    ("web_archive_raw", "image"): "web_archive_raw_html",
    ("web_archive_raw", "other"): "web_archive_raw_html",
    ("web_archive_screenshot", "image"): "web_archive_screenshot",
    ("upload", "html"): "upload",
    ("upload", "image"): "upload",
    ("upload", "pdf"): "upload",
    ("upload", "video"): "upload",
    ("upload", "audio"): "upload",
    ("upload", "other"): "upload",
}


def backfill_types(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    for asset in Asset.objects.all().only("id", "kind"):
        asset_type, file_type = KIND_TO_TYPES.get(asset.kind, ("upload", "other"))
        Asset.objects.filter(pk=asset.pk).update(
            asset_type=asset_type, file_type=file_type
        )


def restore_kind(apps, schema_editor):
    Asset = apps.get_model("assets", "Asset")
    for asset in Asset.objects.all().only("id", "asset_type", "file_type"):
        kind = TYPES_TO_KIND.get((asset.asset_type, asset.file_type), "upload")
        Asset.objects.filter(pk=asset.pk).update(kind=kind)


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0001_initial"),
    ]

    operations = [
        # 1. Add the new columns. They start nullable / with a placeholder
        #    default so we can land them on a populated table; the data
        #    migration immediately backfills real values.
        migrations.AddField(
            model_name="asset",
            name="file_type",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("html", "HTML"),
                    ("image", "Image"),
                    ("pdf", "PDF"),
                    ("video", "Video"),
                    ("audio", "Audio"),
                    ("other", "Other"),
                ],
                default="other",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="asset",
            name="asset_type",
            field=models.CharField(
                max_length=40,
                choices=[
                    ("web_archive_readable", "Web Archive Readable HTML"),
                    ("web_archive_raw", "Web Archive Raw"),
                    ("web_archive_screenshot", "Web Archive Screenshot"),
                    ("block_attachment", "Block Attachment"),
                    ("whiteboard_asset", "Whiteboard Asset"),
                    ("chat_attachment", "Chat Attachment"),
                    ("upload", "User Upload"),
                ],
                default="upload",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="asset",
            name="original_filename",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="asset",
            name="width",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="asset",
            name="height",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        # 2. Backfill from the old kind column.
        migrations.RunPython(backfill_types, restore_kind),
        # 3. Drop the old index + column. The index has to go before the
        #    column or Django complains.
        migrations.RemoveIndex(
            model_name="asset",
            name="assets_user_id_kind_idx",
        ),
        migrations.RemoveField(
            model_name="asset",
            name="kind",
        ),
        # 4. Add the new compound index on the replacement column.
        migrations.AddIndex(
            model_name="asset",
            index=models.Index(
                fields=["user", "asset_type"], name="assets_user_id_asset_type_idx"
            ),
        ),
    ]
