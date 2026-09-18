from html.parser import HTMLParser
from typing import List, Optional, Tuple

from django.test import TestCase
from django.urls import reverse

from knowledge.test.helpers import UserFactory


class _HeadCollector(HTMLParser):
    """Collects the tags a spec-compliant parser puts inside <head>.

    Browsers close </head> implicitly at the first element that isn't
    allowed there, so "is this tag inside the head element" is a
    question about parsing, not about source order. html.parser doesn't
    do that recovery itself, so we model the one rule that bit us: the
    head ends at the first tag outside the permitted set.
    """

    HEAD_CONTENT = {"base", "link", "meta", "noscript", "script", "style", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.head_closed = False
        self.head_tags: List[Tuple[str, dict]] = []
        # The tag that forced the head to end early, if any. This is the
        # actual bug signature - a browser ends the head here and every
        # link below it becomes body content.
        self.closed_early_by: Optional[str] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "head":
            self.in_head = True
            return
        if not self.in_head or self.head_closed:
            return
        if tag in self.HEAD_CONTENT:
            self.head_tags.append((tag, dict(attrs)))
        else:
            # Not permitted in head -> the browser starts the body here.
            self.closed_early_by = tag
            self.head_closed = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.head_closed = True

    def find_link(self, rel: str) -> Optional[dict]:
        for tag, attrs in self.head_tags:
            if tag == "link" and attrs.get("rel") == rel:
                return attrs
        return None


class IndexViewHeadTests(TestCase):
    """The SPA shell's <head> must survive parsing intact.

    A hidden <input> from a csrf_token tag used to sit above the icon
    and manifest links, which closed </head> early and dropped both into
    <body> - where browsers honor neither. That cost the favicon and the
    PWA install prompt, silently, with no console error and valid-looking
    source. These tests pin the shape that keeps them working.
    """

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)

    def _parsed_head(self) -> _HeadCollector:
        response = self.client.get(reverse("knowledge:index"))
        self.assertEqual(response.status_code, 200)
        parser = _HeadCollector()
        parser.feed(response.content.decode())
        return parser

    def test_head_is_not_closed_early_by_a_stray_element(self) -> None:
        # Asserted through the parser rather than by string-matching the
        # source: markup-looking text inside a comment is not an element,
        # and only a parser can tell the difference.
        parser = self._parsed_head()
        self.assertIsNone(
            parser.closed_early_by,
            f"<{parser.closed_early_by}> is not allowed in <head> and ends "
            "it early, dropping every link below it into <body>",
        )

    def test_shell_renders_no_csrf_input(self) -> None:
        response = self.client.get(reverse("knowledge:index"))
        self.assertNotIn(b"csrfmiddlewaretoken", response.content)

    def test_favicon_link_survives_in_head(self) -> None:
        self.assertIsNotNone(
            self._parsed_head().find_link("icon"),
            "no <link rel=icon> left in <head> - something above it "
            "closed the head early",
        )

    def test_manifest_link_survives_in_head(self) -> None:
        self.assertIsNotNone(
            self._parsed_head().find_link("manifest"),
            "no <link rel=manifest> left in <head> - Chrome will report "
            "no manifest and drop the PWA install prompt",
        )

    def test_apple_touch_icon_survives_in_head(self) -> None:
        self.assertIsNotNone(self._parsed_head().find_link("apple-touch-icon"))

    def test_csrf_cookie_is_still_set_on_the_shell(self) -> None:
        response = self.client.get(reverse("knowledge:index"))
        self.assertIn(
            "csrftoken",
            response.cookies,
            "api.js reads the csrftoken cookie; the shell must set it",
        )


class FaviconRouteTests(TestCase):
    def test_root_favicon_redirects_to_the_static_file(self) -> None:
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("knowledge/icons/favicon.ico"))
