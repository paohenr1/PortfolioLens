from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class LandingPageTests(SimpleTestCase):
    @override_settings(INTRINIO_API_KEY="")
    def test_unconfigured_page_is_explicit_and_has_no_price_data(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "research/home.html")
        self.assertContains(response, "Market data unavailable: Intrinio is not configured.")
        self.assertContains(response, 'data-provider-status="not_configured"')
        self.assertContains(response, "No prices, financial metrics, or portfolio results")

    @override_settings(INTRINIO_API_KEY="test-only-never-send-to-browser")
    def test_configured_key_never_claims_verified_data_or_reaches_browser(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "data access is checked when you search.")
        self.assertContains(response, 'data-provider-status="configured_unverified"')
        self.assertNotContains(response, "test-only-never-send-to-browser")
        self.assertNotIn("test-only-never-send-to-browser", str(dict(response.headers)))

    def test_unsafe_methods_are_rejected(self):
        self.assertEqual(self.client.post(reverse("home")).status_code, 405)

    def test_head_is_supported(self):
        response = self.client.head(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    @override_settings(ALLOWED_HOSTS=["research.example.com"], DEBUG=False)
    def test_untrusted_host_is_rejected(self):
        response = self.client.get(reverse("home"), HTTP_HOST="untrusted.example")
        self.assertEqual(response.status_code, 400)

    def test_response_has_browser_security_headers(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertIn("object-src 'none'", response.headers["Content-Security-Policy"])

    def test_page_has_local_assets_and_accessible_structure(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, '<html lang="en">')
        self.assertContains(response, 'href="#main"')
        self.assertContains(response, 'href="/static/research/site.css"')
        self.assertNotContains(response, "<script")
