"""State keywords (TODO/DOING/DONE/LATER/WONTDO) carried as a content
prefix by todo-family blocks."""

import re

# Block types that carry a leading content prefix (e.g. "TODO write docs").
STATE_PREFIXES = {
    "todo": "TODO",
    "doing": "DOING",
    "done": "DONE",
    "later": "LATER",
    "wontdo": "WONTDO",
}


_LEADING_STATE_RE = re.compile(
    rf"^\s*({'|'.join(STATE_PREFIXES.values())})\b", re.IGNORECASE
)
# Anything content auto-detect reads as a todo-family marker.
_STATE_MARKER_RE = re.compile(
    rf"^\s*(?:(?:{'|'.join(STATE_PREFIXES.values())})\b|\[[ xX]\]|☐|☑)",
    re.IGNORECASE,
)


def has_state_marker(content: str) -> bool:
    """True when content starts with a state keyword or checkbox marker,
    i.e. content auto-detect would pick a todo-family type from it."""
    return bool(_STATE_MARKER_RE.match(content or ""))


def keeps_state_type(block_type: str, content: object) -> bool:
    """True when a content-only tool edit should keep a todo-family
    block's type: the block has one and the new content doesn't name a
    state of its own. The web editor relies on auto-detect demoting
    "x" to a bullet; a tool caller that leaves the prefix off just
    forgot it (issue #263)."""
    return (
        isinstance(content, str)
        and block_type in STATE_PREFIXES
        and not has_state_marker(content)
    )


def ensure_state_prefix(content: str, block_type: str) -> str:
    """Make content carry the state keyword for block_type.

    The prefix is what content auto-detect reads the type back from, so
    a todo-family block without one turns into a bullet on the next
    content-only save. A leading keyword for a different state is
    swapped in place (keeping any "KEYWORD:" colon); content of a
    non-state type, or empty content, is returned unchanged."""
    prefix = STATE_PREFIXES.get(block_type)
    if not prefix or not (content or "").strip():
        return content
    match = _LEADING_STATE_RE.match(content)
    if match is None:
        return f"{prefix} {content.lstrip()}"
    if match.group(1).upper() == prefix:
        return content
    return content[: match.start(1)] + prefix + content[match.end(1) :]


def strip_state_prefix(content: str, old_prefix: str) -> str:
    stripped = re.sub(
        rf"^\s*{old_prefix}\b\s*:?\s*", "", content, count=1, flags=re.IGNORECASE
    )
    return stripped
