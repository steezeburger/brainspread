"""Absolute links into the app for outbound messages (Discord embeds).

Shared by reminder delivery and the automations `notify` action so the
"deep link to a block" rules live in one place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge.models import Block


def block_page_url(block: "Block", site_url: str) -> str:
    """Absolute URL to the page containing ``block``.

    Includes a ``#block-<uuid>`` fragment so the editor scrolls straight
    to the block on load (see ``scrollToHashBlock`` in Page.js). Returns
    "" when SITE_URL isn't a real http(s) URL — the default placeholder
    ("0.0.0.0") would produce broken links, and an embed is better off
    without them.
    """
    if not site_url or not site_url.startswith(("http://", "https://")):
        return ""
    if not block.page_id or not block.page.slug:
        return ""
    base = site_url.rstrip("/")
    return f"{base}/knowledge/page/{block.page.slug}/#block-{block.uuid}"
