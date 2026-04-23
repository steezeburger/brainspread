from dataclasses import dataclass
from typing import Optional

import httpx

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; brainspread-archiver/1.0; +https://brainspread.app)"
)
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB - refuse absurd payloads


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    content_type: str
    # Raw bytes as delivered by the server. Used when the response isn't
    # HTML (PDF, image, etc.) so we can store the real file instead of a
    # mojibake UTF-8 decode of it.
    content_bytes: bytes
    # UTF-8 / declared-charset decoding of the body. Only meaningful for
    # text/html-ish responses; for binary content this is best-effort and
    # should not be saved.
    html: str

    @property
    def is_html_like(self) -> bool:
        ct = (self.content_type or "").lower()
        return (
            "text/html" in ct
            or "application/xhtml" in ct
            or "text/plain" in ct
            or not ct
        )


def fetch_url(
    url: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    user_agent: Optional[str] = None,
) -> FetchedPage:
    """
    Fetch a URL and return both the raw body bytes and a best-effort
    decoded string. Raises httpx.HTTPError on network / non-2xx /
    oversized responses; callers translate those into a failure state.
    """
    headers = {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": ("text/html,application/xhtml+xml,application/pdf,image/*,*/*;q=0.8"),
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
        return FetchedPage(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            content_type=content_type,
            content_bytes=response.content,
            html=response.text,
        )
