from dataclasses import dataclass
from typing import Optional

import httpx

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; brainspread-snapshot/1.0; +https://brainspread.app)"
)
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB - refuse absurd payloads


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    content_type: str
    html: str


def fetch_url(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    user_agent: Optional[str] = None,
) -> FetchedPage:
    """
    Fetch a URL and return the decoded HTML body. Raises httpx.HTTPError on
    network / non-2xx / oversized responses; callers translate those into a
    snapshot failure state.
    """
    headers = {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(
        timeout=timeout, follow_redirects=True, headers=headers
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise httpx.HTTPError(f"Response too large: {len(response.content)} bytes")
        content_type = response.headers.get("content-type", "")
        # httpx's .text uses the declared encoding; good enough for HTML.
        return FetchedPage(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
            html=response.text,
        )
