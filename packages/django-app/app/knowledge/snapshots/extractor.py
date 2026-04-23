import html as html_lib
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse


@dataclass
class ExtractedPage:
    title: str = ""
    site_name: str = ""
    author: str = ""
    published_at: Optional[datetime] = None
    og_image_url: str = ""
    favicon_url: str = ""
    canonical_url: str = ""
    excerpt: str = ""
    readable_html: str = ""
    plain_text: str = ""
    word_count: int = 0
    meta: Dict[str, str] = field(default_factory=dict)


# Tags whose inner text is noise, not content.
_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "nav",
    "aside",
    "footer",
    "header",
    "form",
    "svg",
    "template",
    "iframe",
    "object",
    "embed",
}

# Tags to preserve in the readable HTML body.
_KEEP_TAGS = {
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "code",
    "em",
    "strong",
    "b",
    "i",
    "a",
    "img",
    "figure",
    "figcaption",
    "hr",
}


class _MetaExtractor(HTMLParser):
    """
    First pass: pull title, meta tags, and link rels. Doesn't touch the body.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._in_head = False
        self.meta: Dict[str, str] = {}
        self.links: Dict[str, str] = {}  # rel -> href

    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        if tag == "head":
            self._in_head = True
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            attrs_dict = {k.lower(): (v or "") for k, v in attrs}
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = attrs_dict.get("content", "")
            if name and content and name not in self.meta:
                self.meta[name] = content
        elif tag == "link":
            attrs_dict = {k.lower(): (v or "") for k, v in attrs}
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "")
            if rel and href and rel not in self.links:
                self.links[rel] = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


class _ReadableExtractor(HTMLParser):
    """
    Second pass: walk the body, drop noisy tags, keep a small HTML subset
    plus the plain text.

    This is intentionally dumb. Readability-level extraction needs a real
    library (readability-lxml, trafilatura); this fallback just produces
    something usable so v1 works without new deps. Swap later.
    """

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._skip_depth = 0
        self._in_body = False
        self._parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "body":
            self._in_body = True
            return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth or not self._in_body:
            return
        if tag in _KEEP_TAGS:
            attrs_dict = {k.lower(): (v or "") for k, v in attrs}
            if tag == "a":
                href = attrs_dict.get("href", "")
                if href and self.base_url:
                    href = urljoin(self.base_url, href)
                self._parts.append(f'<a href="{html_lib.escape(href)}">')
            elif tag == "img":
                src = attrs_dict.get("src", "")
                alt = attrs_dict.get("alt", "")
                if src and self.base_url:
                    src = urljoin(self.base_url, src)
                self._parts.append(
                    f'<img src="{html_lib.escape(src)}" '
                    f'alt="{html_lib.escape(alt)}" />'
                )
            else:
                self._parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self._in_body = False
            return
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth or not self._in_body:
            return
        if tag in _KEEP_TAGS and tag != "img" and tag != "br" and tag != "hr":
            self._parts.append(f"</{tag}>")

    def handle_startendtag(self, tag: str, attrs) -> None:  # type: ignore[override]
        # Handles <br/>, <img/>, etc. Delegate to starttag logic.
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not self._in_body:
            return
        if not data.strip():
            # Preserve a single space rather than pile up whitespace.
            if self._parts and not self._parts[-1].endswith(" "):
                self._parts.append(" ")
                self._text_parts.append(" ")
            return
        escaped = html_lib.escape(data)
        self._parts.append(escaped)
        self._text_parts.append(data)

    def result(self) -> tuple[str, str]:
        html_body = "".join(self._parts)
        text = re.sub(r"\s+", " ", "".join(self._text_parts)).strip()
        return html_body, text


def _parse_published_at(meta: Dict[str, str]) -> Optional[datetime]:
    """Try a handful of common OG/article date meta fields."""
    candidates = [
        meta.get("article:published_time"),
        meta.get("og:article:published_time"),
        meta.get("datepublished"),
        meta.get("date"),
        meta.get("pubdate"),
    ]
    for raw in candidates:
        if not raw:
            continue
        # datetime.fromisoformat in 3.11+ parses most ISO 8601 variants;
        # strip trailing Z which it doesn't accept pre-3.11.
        cleaned = raw.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            continue
    return None


def _infer_site_name(meta: Dict[str, str], final_url: str) -> str:
    if meta.get("og:site_name"):
        return meta["og:site_name"]
    if final_url:
        host = urlparse(final_url).netloc
        # Drop common "www." prefix for prettier display.
        return host[4:] if host.startswith("www.") else host
    return ""


def extract_readable(html: str, final_url: str = "") -> ExtractedPage:
    """
    Parse a fetched HTML document into an ExtractedPage. Never raises -
    missing fields come back as empty strings so partial extractions still
    store something useful.
    """
    meta_parser = _MetaExtractor()
    try:
        meta_parser.feed(html)
        meta_parser.close()
    except Exception:
        # HTMLParser can trip on malformed markup. Fall through with
        # whatever we got so far rather than failing the whole capture.
        pass

    body_parser = _ReadableExtractor(base_url=final_url)
    try:
        body_parser.feed(html)
        body_parser.close()
    except Exception:
        pass
    readable_html, plain_text = body_parser.result()

    meta = meta_parser.meta
    title = (
        meta.get("og:title") or meta.get("twitter:title") or meta_parser.title.strip()
    )

    excerpt = (
        meta.get("og:description")
        or meta.get("description")
        or meta.get("twitter:description")
        or plain_text[:280]
    )
    excerpt = excerpt.strip()

    og_image = meta.get("og:image") or meta.get("twitter:image") or ""
    if og_image and final_url:
        og_image = urljoin(final_url, og_image)

    favicon = (
        meta_parser.links.get("icon")
        or meta_parser.links.get("shortcut icon")
        or meta_parser.links.get("apple-touch-icon")
        or ""
    )
    if favicon and final_url:
        favicon = urljoin(final_url, favicon)
    elif not favicon and final_url:
        parsed = urlparse(final_url)
        favicon = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

    canonical = meta_parser.links.get("canonical") or meta.get("og:url") or ""
    if canonical and final_url:
        canonical = urljoin(final_url, canonical)

    author = meta.get("author") or meta.get("article:author") or ""

    word_count = len(plain_text.split()) if plain_text else 0

    return ExtractedPage(
        title=title,
        site_name=_infer_site_name(meta, final_url),
        author=author,
        published_at=_parse_published_at(meta),
        og_image_url=og_image,
        favicon_url=favicon,
        canonical_url=canonical,
        excerpt=excerpt,
        readable_html=readable_html,
        plain_text=plain_text,
        word_count=word_count,
        meta=meta,
    )
