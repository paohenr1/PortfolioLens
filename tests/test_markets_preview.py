"""Design fixtures must never become a production market-data source."""

from dataclasses import replace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class MarketsPreviewTests(SimpleTestCase):
    @override_settings(DEBUG=True, PRIVATE_SITE=False)
    def test_local_preview_has_explicit_sample_labels_without_provider_requests(self):
        with patch("httpx.Client.send", side_effect=AssertionError("Unexpected network request")):
            response = self.client.get(reverse("markets_preview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Illustrative data only")
        self.assertContains(response, "not the complete S&amp;P 500")
        self.assertContains(response, 'aria-label="Color theme"')
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])

    @override_settings(DEBUG=False, PRIVATE_SITE=False)
    def test_preview_is_not_available_without_debug(self):
        self.assertEqual(self.client.get(reverse("markets_preview")).status_code, 404)

    @override_settings(DEBUG=True, PRIVATE_SITE=False)
    def test_production_environment_cannot_expose_preview_even_with_debug_override(self):
        with override_settings(ENVIRONMENT=replace(settings.ENVIRONMENT, name="production")):
            self.assertEqual(self.client.get(reverse("markets_preview")).status_code, 404)

    @override_settings(DEBUG=True, PRIVATE_SITE=False)
    def test_preview_rejects_writes(self):
        self.assertEqual(self.client.post(reverse("markets_preview")).status_code, 405)

    @override_settings(DEBUG=True, PRIVATE_SITE=False, INTRINIO_API_KEY="")
    def test_normal_homepage_does_not_contain_sample_market_values(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "5,842.47")
        self.assertNotContains(response, "sample session")
