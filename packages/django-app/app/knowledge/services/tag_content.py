"""Inline ``#slug`` hashtags in block content — the durable home of a
block's tags. SyncBlockTagsCommand rebuilds the Block.pages links from
these on every content save, so a link with no hashtag behind it is
invisible on the block and vanishes on its next edit."""

import re
from typing import Iterable

# Slugs the hashtag sync can parse back out of content.
TAGGABLE_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def tag_occurrence_re(slug: str) -> re.Pattern:
    """Matches a live ``#slug`` occurrence in block content — the same
    shape the tag sync scans for (backslash-escaped ``\\#slug`` excluded,
    no partial-slug matches)."""
    return re.compile(rf"(?<!\\)#{re.escape(slug)}(?![A-Za-z0-9_-])")


def has_tag(content: str, slug: str) -> bool:
    return bool(tag_occurrence_re(slug).search(content or ""))


def append_tags(content: str, slugs: Iterable[str]) -> str:
    """Append ``#slug`` for each slug not already in content to the end
    of the first line. Idempotent."""
    content = content or ""
    to_add = [s for s in dict.fromkeys(slugs) if not has_tag(content, s)]
    if not to_add:
        return content
    lines = content.split("\n")
    suffix = " ".join(f"#{s}" for s in to_add)
    lines[0] = f"{lines[0].rstrip()} {suffix}".strip()
    return "\n".join(lines)


def remove_tags(content: str, slugs: Iterable[str]) -> str:
    """Strip every live ``#slug`` occurrence, tidying the whitespace the
    removal leaves behind. Returns content unchanged when none matched."""
    content = content or ""
    new_content = content
    for slug in slugs:
        new_content = tag_occurrence_re(slug).sub("", new_content)
    if new_content == content:
        return content
    new_content = re.sub(r"[ \t]{2,}", " ", new_content)
    return "\n".join(line.rstrip() for line in new_content.split("\n"))
