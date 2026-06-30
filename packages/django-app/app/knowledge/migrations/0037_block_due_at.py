from datetime import datetime, time

import pytz
from django.db import migrations, models


def _resolve_tz(tz_name):
    try:
        return pytz.timezone(tz_name or "UTC")
    except pytz.UnknownTimeZoneError:
        return pytz.UTC


def backfill_due_at(apps, schema_editor):
    """Recompute each migrated due_at as user-local midnight.

    The AlterField above casts the old `scheduled_for` date to a datetime
    at midnight in the connection timezone (UTC). For an all-day item we
    want the stored instant to read back on the right calendar date in the
    owner's timezone, so re-localize: take the UTC calendar date and pin it
    to local midnight. All pre-existing rows are all-day (due_at_has_time
    stays False).
    """
    Block = apps.get_model("knowledge", "Block")
    utc = pytz.UTC
    blocks = Block.objects.filter(due_at__isnull=False).select_related("user")
    for block in blocks.iterator():
        cal_date = block.due_at.astimezone(utc).date()
        tz = _resolve_tz(block.user.timezone)
        local_midnight = tz.localize(datetime.combine(cal_date, time.min))
        block.due_at = local_midnight.astimezone(utc)
        block.due_at_has_time = False
        block.save(update_fields=["due_at", "due_at_has_time"])


def _rename_filter_keys(node):
    """Recursively rename any ``scheduled_for`` field key to ``due_at`` in a
    filter spec (leaves look like ``{"scheduled_for": {"lt": "today"}}``)."""
    if isinstance(node, dict):
        return {
            ("due_at" if k == "scheduled_for" else k): _rename_filter_keys(v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_rename_filter_keys(v) for v in node]
    return node


def _rename_sort_fields(sort):
    """Rename ``{"field": "scheduled_for"}`` entries in a sort list. Returns
    ``(new_sort, changed)``."""
    if not isinstance(sort, list):
        return sort, False
    changed = False
    out = []
    for item in sort:
        if isinstance(item, dict) and item.get("field") == "scheduled_for":
            item = {**item, "field": "due_at"}
            changed = True
        out.append(item)
    return out, changed


def rename_saved_view_fields(apps, schema_editor):
    """Rewrite saved-view filter/sort JSON that references the old field name.

    Covers the seeded ``overdue`` view and any user-created views — without
    this their filters silently stop matching once the model field is gone.
    """
    SavedView = apps.get_model("knowledge", "SavedView")
    for view in SavedView.objects.all().iterator():
        dirty = False
        if view.filter:
            new_filter = _rename_filter_keys(view.filter)
            if new_filter != view.filter:
                view.filter = new_filter
                dirty = True
        new_sort, sort_changed = _rename_sort_fields(view.sort or [])
        if sort_changed:
            view.sort = new_sort
            dirty = True
        if dirty:
            view.save(update_fields=["filter", "sort"])


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0036_savedview_dates_relative_to_daily"),
    ]

    operations = [
        migrations.RenameField(
            model_name="block",
            old_name="scheduled_for",
            new_name="due_at",
        ),
        migrations.AlterField(
            model_name="block",
            name="due_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When this block is due (all-day unless due_at_has_time)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="block",
            name="due_at_has_time",
            field=models.BooleanField(
                default=False,
                help_text="True when due_at carries a meaningful time of day",
            ),
        ),
        # The (user, scheduled_for) index follows the column rename, but its
        # auto-generated name is derived from the field name, so rename it to
        # the (user, due_at) name Django now expects. RenameIndex (rather than
        # remove+add) keeps this reversible — a remove+add would reference the
        # old field name on reverse, before the column rename is undone.
        migrations.RenameIndex(
            model_name="block",
            new_name="blocks_user_id_f99b9a_idx",
            old_name="blocks_user_id_e91738_idx",
        ),
        # Help-text example referenced the old field name.
        migrations.AlterField(
            model_name="savedview",
            name="sort",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Ordering, e.g. [{"field": "due_at", "dir": "asc"}]',
            ),
        ),
        migrations.RunPython(backfill_due_at, migrations.RunPython.noop),
        migrations.RunPython(rename_saved_view_fields, migrations.RunPython.noop),
    ]
