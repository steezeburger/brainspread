from django.test import TestCase


class ServiceWorkerViewTestCase(TestCase):
    """The service worker must be reachable at /knowledge/sw.js (not
    /static/...) so its default scope covers the whole SPA - see
    knowledge.views.service_worker."""

    def test_served_at_spa_root_with_js_content_type(self):
        response = self.client.get("/knowledge/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")

    def test_accessible_without_authentication(self):
        # A service worker registers before the app knows whether the
        # user is logged in, so this must never redirect to login.
        response = self.client.get("/knowledge/sw.js")

        self.assertEqual(response.status_code, 200)

    def test_never_cached_by_the_browser(self):
        response = self.client.get("/knowledge/sw.js")

        self.assertIn("no-store", response["Cache-Control"])

    def test_cache_name_is_tied_to_static_version(self):
        from django.conf import settings

        response = self.client.get("/knowledge/sw.js")
        content = response.content.decode()

        self.assertIn(f"brainspread-shell-{settings.STATIC_VERSION}", content)

    def test_precaches_the_app_shell_static_assets(self):
        response = self.client.get("/knowledge/sw.js")
        content = response.content.decode()

        self.assertIn("/static/knowledge/js/app.js", content)
        self.assertIn("/static/knowledge/css/app.css", content)
        self.assertIn("/static/knowledge/manifest.json", content)
