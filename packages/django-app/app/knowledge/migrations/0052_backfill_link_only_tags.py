import re

from django.db import migrations

TAGGABLE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")
# A link-only #automation would turn the block into an automation
# definition once written into content. Leave those alone.
SKIPPED_SLUGS = {"automation"}


def _has_tag(content: str, slug: str) -> bool:
    return bool(re.search(rf"(?<!\\)#{re.escape(slug)}(?![A-Za-z0-9_-])", content))


def _append_tags(content: str, slugs) -> str:
    to_add = [s for s in slugs if not _has_tag(content, s)]
    if not to_add:
        return content
    lines = content.split("\n")
    suffix = " ".join(f"#{s}" for s in to_add)
    lines[0] = f"{lines[0].rstrip()} {suffix}".strip()
    return "\n".join(lines)


def backfill_link_only_tags(apps, schema_editor):
    """The old tag_block tool (issue #261) only wrote the Block.pages link,
    so those tags never showed on the block and were dropped by the tag
    sync on its next content edit. Write them into the content."""
    Block = apps.get_model("knowledge", "Block")
    batch = []
    blocks = (
        Block.objects.exclude(block_type="code")
        .prefetch_related("pages")
        .only("id", "content", "page_id")
    )
    for block in blocks.iterator(chunk_size=500):
        content = block.content or ""
        slugs = sorted(
            page.slug
            for page in block.pages.all()
            if page.is_active
            and page.id != block.page_id
            and page.page_type != "daily"
            and page.slug not in SKIPPED_SLUGS
            and TAGGABLE_SLUG_RE.match(page.slug)
        )
        new_content = _append_tags(content, slugs)
        if new_content != content:
            block.content = new_content
            batch.append(block)
        if len(batch) >= 500:
            Block.objects.bulk_update(batch, ["content"])
            batch = []
    if batch:
        Block.objects.bulk_update(batch, ["content"])


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0051_backfill_todo_state_prefixes"),
    ]

    operations = [
        migrations.RunPython(backfill_link_only_tags, migrations.RunPython.noop),
    ]
