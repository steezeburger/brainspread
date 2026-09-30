import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

from lxml.html import fromstring as lxml_fromstring
from lxml.html import tostring as lxml_tostring
from readability import Document

logger = logging.getLogger(__name__)


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


# Tags whose inner text is noise, not content. Only used by the last-resort
# fallback parser below.
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

# Tags to preserve in the readable HTML body (fallback parser only).
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


class _FallbackReadableExtractor(HTMLParser):
    """
    Last-resort body extraction, used only when readability-lxml can't find
    a usable article in the page (e.g. it comes back empty). Intentionally
    dumb - see extract_readable() for the real (readability-lxml-backed)
    extraction path.
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

    def result(self) -> Tuple[str, str]:
        html_body = "".join(self._parts)
        text = re.sub(r"\s+", " ", "".join(self._text_parts)).strip()
        return html_body, text


def _fallback_extract_body(html: str, final_url: str) -> Tuple[str, str]:
    body_parser = _FallbackReadableExtractor(base_url=final_url)
    try:
        body_parser.feed(html)
        body_parser.close()
    except Exception:
        # HTMLParser can trip on malformed markup. Fall through with
        # whatever we got so far rather than failing the whole capture.
        pass
    return body_parser.result()


def _strip_noise_tags(html: str) -> str:
    """
    Drop nav/header/footer/script/etc. before handing the document to
    readability. Readability's own candidate scoring is class/id-driven
    (it doesn't treat e.g. <nav> as inherently unlikely), so on small or
    unusually-marked-up pages it can otherwise fall through to "return the
    whole body" and drag chrome back in.
    """
    try:
        tree = lxml_fromstring(html)
    except Exception:
        return html
    for el in list(tree.iter(*_SKIP_TAGS)):
        el.drop_tree()
    return lxml_tostring(tree, encoding="unicode")


def _run_readability(html: str, final_url: str) -> Tuple[str, str, str]:
    """
    Run the article through readability-lxml (a port of Mozilla's
    Readability). It scores candidate DOM nodes to find the actual article
    body, drops ads/boilerplate, and - when given a base url - rewrites
    relative hrefs/srcs to absolute ones in the same pass.

    Returns (readable_html, plain_text, short_title). Can raise on
    thoroughly broken input; callers treat that as "no readable body".
    """
    document = Document(_strip_noise_tags(html), url=final_url or None)
    readable_html = document.summary(html_partial=True) or ""
    plain_text = ""
    if readable_html.strip():
        tree = lxml_fromstring(readable_html)
        plain_text = re.sub(r"\s+", " ", tree.text_content()).strip()
    short_title = document.short_title() or ""
    return readable_html, plain_text, short_title


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

    Body extraction is delegated to readability-lxml; metadata (title,
    author, dates, images, canonical url, favicon) comes from a plain
    meta/link-tag pass, since that's cheap, precise, and readability
    doesn't attempt most of it anyway.
    """
    meta_parser = _MetaExtractor()
    try:
        meta_parser.feed(html)
        meta_parser.close()
    except Exception:
        pass

    readable_html = ""
    plain_text = ""
    short_title = ""
    try:
        readable_html, plain_text, short_title = _run_readability(html, final_url)
    except Exception as exc:  # noqa: BLE001 - readability is best-effort
        logger.warning("readability extraction failed for %s: %s", final_url, exc)

    if not plain_text.strip():
        # readability found nothing usable (or blew up) - fall back to the
        # dumb tag-stripping parser so we still store something.
        fallback_html, fallback_text = _fallback_extract_body(html, final_url)
        if fallback_text.strip():
            readable_html, plain_text = fallback_html, fallback_text

    meta = meta_parser.meta
    title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or short_title
        or meta_parser.title.strip()
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
