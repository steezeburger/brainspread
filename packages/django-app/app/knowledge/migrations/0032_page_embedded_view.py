"""Refactor query embeds out of the Block table.

Why this migration exists
-------------------------

Migration 0030 prototyped query embeds as ``Block(block_type='query',
query_view=<SavedView>)``. After staging dogfood that turned out to
be a leaky abstraction: an embed has no content, no parent, no
properties, no asset — it's a pointer record, not a block. Squatting
those fields on Block also opens up weird recursion paths (a
``has_tag`` query that matches the embed block itself) and forces
embed-specific UI to plumb through BlockComponent.

This migration introduces ``PageEmbeddedView`` as the embed's own
table, copies any existing ``Block(block_type='query')`` rows over,
deletes the originals, and drops the ``Block.query_view`` FK + the
``query`` choice from ``Block.block_type``. After this runs, embeds
live in ``page_embedded_views`` and the Block table is back to being
about content blocks.

Forward-only — the data move is destructive and not worth a reverse
migration; staging is the only environment that has any rows.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _migrate_query_blocks(apps, schema_editor):
    """Copy each ``Block(block_type='query')`` to a PageEmbeddedView and
    delete the Block. We preserve ``order`` and ``user``/``page``/
    ``saved_view`` linkage; ``collapsed`` defaults to False (the old
    Block.collapsed flag wasn't surfaced for query blocks).

    Skips rows where ``query_view`` is null — those are dangling embeds
    (the SavedView was deleted under SET_NULL); they have nothing to
    point at, so we just delete them along with the originals.
    """
    Block = apps.get_model("knowledge", "Block")
    PageEmbeddedView = apps.get_model("knowledge", "PageEmbeddedView")

    moved_block_ids = []
    for block in Block.objects.filter(block_type="query"):
        if block.query_view_id is None:
            moved_block_ids.append(block.id)
            continue
        # Respect the unique_together(page, saved_view) — if a duplicate
        # somehow exists from manual API calls, drop the dupe rather than
        # crash the migration.
        existing = PageEmbeddedView.objects.filter(
            page_id=block.page_id, saved_view_id=block.query_view_id
        ).first()
        if existing is None:
            PageEmbeddedView.objects.create(
                user_id=block.user_id,
                page_id=block.page_id,
                saved_view_id=block.query_view_id,
                order=block.order or 0,
                collapsed=False,
            )
        moved_block_ids.append(block.id)

    if moved_block_ids:
        Block.objects.filter(id__in=moved_block_ids).delete()


def _noop_reverse(apps, schema_editor):
    """No reverse — see module docstring. Provided so makemigrations
    --check / sqlmigrate don't complain about a missing reverse."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0031_seed_system_views"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PageEmbeddedView",
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("modified_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "uuid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Display order within the page's embedded-views section",
                    ),
                ),
                (
                    "collapsed",
                    models.BooleanField(
                        default=False,
                        help_text="When true, the embed renders header-only on the page",
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="embedded_views",
                        to="knowledge.page",
                    ),
                ),
                (
                    "saved_view",
                    models.ForeignKey(
                        help_text="The view whose results render in this slot",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="embedded_on",
                        to="knowledge.savedview",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page_embedded_views",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "page_embedded_views",
                "ordering": ("order", "created_at"),
            },
        ),
        migrations.AddIndex(
            model_name="pageembeddedview",
            index=models.Index(
                fields=["page", "order"],
                name="page_embed_page_order_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="pageembeddedview",
            index=models.Index(
                fields=["user"],
                name="page_embed_user_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="pageembeddedview",
            unique_together={("page", "saved_view")},
        ),
        migrations.RunPython(_migrate_query_blocks, _noop_reverse),
        migrations.RemoveField(
            model_name="block",
            name="query_view",
        ),
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
