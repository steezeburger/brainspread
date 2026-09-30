from django.test import TestCase
from django.urls import reverse


class ServiceWorkerViewTests(TestCase):
    """The service worker must be reachable at /knowledge/sw.js so its
    default scope covers the whole SPA (see knowledge/views.py:280).
    Unauthenticated too - the browser requests it before login.
    """

    def test_service_worker_returns_200_as_javascript(self) -> None:
        response = self.client.get(reverse("knowledge:service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")

    def test_service_worker_is_not_cached(self) -> None:
        response = self.client.get(reverse("knowledge:service_worker"))
        self.assertIn("no-store", response["Cache-Control"])
