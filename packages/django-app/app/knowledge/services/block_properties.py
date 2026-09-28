"""Pure `key:: value` property extraction from block content.

Parsing has no DB I/O — callers (currently CreateBlockCommand,
UpdateBlockCommand, AddTemplateBlocksToPageCommand) decide whether the
result differs from what's stored and, if so, persist it via
BlockRepository.update_properties().
"""

import re
from typing import Dict, Optional

# Property keys managed by the UI (the resize handle and the "show as
# raw" / "reset size" entries in the block context menu) rather than by
# the user typing `key:: value` into block content. Kept out of the
# content-driven property sync below so a routine block edit doesn't
# clobber them — drag to resize, then type anywhere in the block, and
# the persisted width would otherwise vanish on the next page load.
UI_MANAGED_PROPERTY_KEYS = frozenset({"size", "render"})


def extract_properties_from_content(
    content: str, current_properties: Optional[Dict[str, str]]
) -> Dict[str, str]:
    """`key:: value` properties parsed from `content`, merged with the
    UI-managed keys already present in `current_properties`. Empty
    content is a no-op — returns `current_properties` unchanged so a
    content-less block never has its properties wiped."""
    current = current_properties or {}
    if not content:
        return dict(current)

    extracted_properties: Dict[str, str] = {}

    # First: Handle line-start properties (can have multi-word values)
    line_pattern = r"^([a-zA-Z0-9_-]+)::\s*(.+)$"
    for line in content.split("\n"):
        match = re.match(line_pattern, line.strip())
        if match:
            key, value = match.groups()
            # For line-start properties, strip out any inline properties from the value
            # Split value and take only until the first inline property
            value_words = value.split()
            clean_value_words = []
            for word in value_words:
                if "::" in word and re.match(r"^[a-zA-Z0-9_-]+::", word):
                    break  # Stop at first inline property
                clean_value_words.append(word)
            if clean_value_words:
                extracted_properties[key] = " ".join(clean_value_words)

    # Second: Handle inline properties (single word values)
    inline_pattern = r"([a-zA-Z0-9_-]+)::\s*([^\s]+)"
    for line in content.split("\n"):
        # Find all inline properties in each line
        matches = re.findall(inline_pattern, line)
        for key, value in matches:
            # Only add if not already found as line-start property
            if key not in extracted_properties:
                extracted_properties[key] = value.strip()

    preserved = {k: current[k] for k in UI_MANAGED_PROPERTY_KEYS if k in current}
    return {**extracted_properties, **preserved}
