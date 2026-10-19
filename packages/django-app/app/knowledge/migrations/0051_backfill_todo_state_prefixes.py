import re

from django.db import migrations

STATE_PREFIXES = {
    "todo": "TODO",
    "doing": "DOING",
    "done": "DONE",
    "later": "LATER",
    "wontdo": "WONTDO",
}
LEADING_STATE_RE = re.compile(
    rf"^\s*({'|'.join(STATE_PREFIXES.values())})\b", re.IGNORECASE
)


def _with_prefix(content: str, block_type: str) -> str:
    prefix = STATE_PREFIXES[block_type]
    if not (content or "").strip():
        return content
    match = LEADING_STATE_RE.match(content)
    if match is None:
        return f"{prefix} {content.lstrip()}"
    if match.group(1).upper() == prefix:
        return content
    return content[: match.start(1)] + prefix + content[match.end(1) :]


def backfill_prefixes(apps, schema_editor):
    """Todo-family blocks created through tools before issue #263 could
    save content without their state keyword, which the next content-only
    save reads back as a bullet. Write the keyword in."""
    Block = apps.get_model("knowledge", "Block")
    batch = []
    blocks = Block.objects.filter(block_type__in=STATE_PREFIXES.keys()).only(
        "id", "content", "block_type"
    )
    for block in blocks.iterator(chunk_size=500):
        content = _with_prefix(block.content, block.block_type)
        if content != block.content:
            block.content = content
            batch.append(block)
        if len(batch) >= 500:
            Block.objects.bulk_update(batch, ["content"])
            batch = []
    if batch:
        Block.objects.bulk_update(batch, ["content"])


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0050_merge_block_revision_and_soft_delete"),
    ]

    operations = [
        migrations.RunPython(backfill_prefixes, migrations.RunPython.noop),
    ]
