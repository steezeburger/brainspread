"""Shared block_type vocabulary.

CONTEXT.md gives these sets their words: a *todo* is a block whose kind
tracks a piece of work, it is *open* while it sits in the queue, and
*completed* once it has left the queue - whether or not it got done.

They live here so a new todo kind is one edit rather than a grep. Tuples
rather than sets because a couple of callers serialize them into stored
query specs, where the order needs to be stable.

Note: the seeded system-view specs in migration 0031 carry their own
frozen copies of these lists, as migrations always do. Changing a set
here does not rewrite views that were already seeded.
"""

from typing import Tuple

OPEN_TODO_TYPES: Tuple[str, ...] = ("todo", "doing", "later")

# Slug of the tag that marks a block as an automation definition. Lives
# here (import-free module) so models can use it without pulling in the
# services layer; knowledge.services.automation_spec re-exports it.
AUTOMATION_TAG_SLUG = "automation"

COMPLETED_TODO_TYPES: Tuple[str, ...] = ("done", "wontdo")

# Every block_type that tracks work, as against bullet / heading /
# quote / code / divider, which track none.
TODO_TYPES: Tuple[str, ...] = OPEN_TODO_TYPES + COMPLETED_TODO_TYPES
