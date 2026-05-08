"""Bundled system-view specs (issue #60).

System views are seeded per-user with ``is_system=True`` so the API can
keep them read-only. The seed migration (0031) carries its own copy of
this spec list — by Django convention migrations don't import live
models — so when you tweak a view here, also bump it in the migration
(or ship a follow-up data migration that ``update_or_create``\\s).
"""

from typing import Any, Dict, List

from knowledge.models import SavedView
from knowledge.repositories import SavedViewRepository

OVERDUE_FILTER: Dict[str, Any] = {
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

DONE_THIS_WEEK_FILTER: Dict[str, Any] = {
    "all": [
        {"block_type": {"in": ["done", "wontdo"]}},
        {"completed_at": {"gte": "7 days ago"}},
    ]
}

DONE_THIS_WEEK_SORT = [
    {"field": "completed_at", "dir": "desc"},
]

SYSTEM_VIEW_SPECS: List[Dict[str, Any]] = [
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


def seed_system_views_for_user(user) -> List[SavedView]:
    """Idempotently seed system views for ``user``. Returns the resulting rows.

    Used by the user-registration flow so a freshly-registered account
    starts with the same bundled views the existing-user backfill
    migration created. Re-running is safe: each spec ``update_or_create``\\s
    on (user, slug) and refreshes the filter/sort.
    """
    rows: List[SavedView] = []
    for spec in SYSTEM_VIEW_SPECS:
        existing = SavedViewRepository.get_by_slug(spec["slug"], user)
        if existing:
            rows.append(
                SavedViewRepository.update(
                    existing,
                    name=spec["name"],
                    description=spec["description"],
                    filter=spec["filter"],
                    sort=spec["sort"],
                    is_system=True,
                )
            )
            continue
        rows.append(
            SavedViewRepository.create(
                user=user,
                name=spec["name"],
                slug=spec["slug"],
                description=spec["description"],
                filter_spec=spec["filter"],
                sort=spec["sort"],
                is_system=True,
            )
        )
    return rows
