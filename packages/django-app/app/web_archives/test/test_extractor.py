from django.test import SimpleTestCase

from web_archives.pipeline import extract_readable


class TestExtractor(SimpleTestCase):
    def test_extracts_basic_metadata(self):
        html = """
        <html><head>
          <title>Plain Title</title>
          <meta name="description" content="desc" />
          <meta name="author" content="Alice" />
          <link rel="canonical" href="https://example.com/a" />
        </head><body><p>Hello world.</p></body></html>
        """
        result = extract_readable(html, final_url="https://example.com/a")
        self.assertEqual(result.title, "Plain Title")
        self.assertEqual(result.author, "Alice")
        self.assertEqual(result.excerpt, "desc")
        self.assertEqual(result.canonical_url, "https://example.com/a")
        self.assertIn("Hello world", result.plain_text)
        self.assertEqual(result.word_count, 2)

    def test_prefers_og_title_when_available(self):
        html = """
        <html><head>
          <title>Plain Title</title>
          <meta property="og:title" content="OG Title" />
        </head><body><p>x</p></body></html>
        """
        result = extract_readable(html)
        self.assertEqual(result.title, "OG Title")

    def test_skips_script_and_nav_content(self):
        html = """
        <html><body>
          <nav>site nav links here</nav>
          <script>var secret = 1;</script>
          <article><p>The main body.</p></article>
          <footer>footer content</footer>
        </body></html>
        """
        result = extract_readable(html)
        self.assertIn("main body", result.plain_text)
        self.assertNotIn("site nav", result.plain_text)
        self.assertNotIn("secret", result.plain_text)
        self.assertNotIn("footer content", result.plain_text)

    def test_resolves_relative_urls_with_final_url(self):
        html = """
        <html><head>
          <meta property="og:image" content="/hero.png" />
          <link rel="icon" href="/favicon.ico" />
        </head><body><p>x</p></body></html>
        """
        result = extract_readable(html, final_url="https://example.com/page")
        self.assertEqual(result.og_image_url, "https://example.com/hero.png")
        self.assertEqual(result.favicon_url, "https://example.com/favicon.ico")

    def test_site_name_falls_back_to_host(self):
        html = "<html><body><p>x</p></body></html>"
        result = extract_readable(html, final_url="https://www.example.com/a")
        self.assertEqual(result.site_name, "example.com")

    def test_handles_malformed_html_without_raising(self):
        html = "<html><body><p>unterminated <b>bold"
        result = extract_readable(html)
        self.assertIn("unterminated", result.plain_text)

    def test_parses_published_at_from_article_meta(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2024-03-02T12:00:00Z" />
        </head><body><p>x</p></body></html>
        """
        result = extract_readable(html)
        self.assertIsNotNone(result.published_at)
        self.assertEqual(result.published_at.year, 2024)
