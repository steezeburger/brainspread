"""Seed bundled system views for every existing user (issue #60).

Creates two ``is_system=True`` SavedView rows per user:

- **overdue** — open scheduled blocks past today. Same predicate that
  drove the hard-coded Overdue section before #60; the daily-page swap
  now reads from this row.
- **done-this-week** — completed_at within the last 7 days.

System views are read-only for the user (the API rejects edits / deletes
on rows where ``is_system=True``). Cloning makes a normal user view they
can tweak.

A companion forwards step also handles new users — but new-user seeding
is wired through the User-creation path elsewhere; this migration covers
the existing-user backfill.
"""

from django.db import migrations

OVERDUE_FILTER = {
    "all": [
        {"block_type": {"in": ["todo", "doing", "later"]}},
        {"scheduled_for": {"lt": "today"}},
        {"completed_at": {"is_null": True}},
    ]
}

OVERDUE_SORT = [
    {"field": "scheduled_for", "dir": "asc"},
    {"field": "order", "dir": "asc"},
]

DONE_THIS_WEEK_FILTER = {
    "all": [
        {"block_type": {"in": ["done", "wontdo"]}},
        {"completed_at": {"gte": "7 days ago"}},
    ]
}

DONE_THIS_WEEK_SORT = [
    {"field": "completed_at", "dir": "desc"},
]

SYSTEM_VIEWS = [
    {
        "slug": "overdue",
        "name": "Overdue",
        "description": "Open todos / doings / laters scheduled before today.",
        "filter": OVERDUE_FILTER,
        "sort": OVERDUE_SORT,
    },
    {
        "slug": "done-this-week",
        "name": "Done this week",
        "description": "Blocks completed in the last 7 days.",
        "filter": DONE_THIS_WEEK_FILTER,
        "sort": DONE_THIS_WEEK_SORT,
    },
]


def seed_system_views(apps, schema_editor):
    User = apps.get_model("core", "User")
    SavedView = apps.get_model("knowledge", "SavedView")

    for user in User.objects.all():
        for spec in SYSTEM_VIEWS:
            # update_or_create so re-running the migration (or a downstream
            # tweak shipped via another migration) refreshes the seeded
            # filter/sort without dropping is_system.
            SavedView.objects.update_or_create(
                user=user,
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "filter": spec["filter"],
                    "sort": spec["sort"],
                    "is_system": True,
                },
            )


def unseed_system_views(apps, schema_editor):
    SavedView = apps.get_model("knowledge", "SavedView")
    SavedView.objects.filter(
        is_system=True,
        slug__in=[s["slug"] for s in SYSTEM_VIEWS],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0030_savedview"),
        ("core", "0014_alter_user_theme"),
    ]

    operations = [
        migrations.RunPython(seed_system_views, reverse_code=unseed_system_views),
    ]
