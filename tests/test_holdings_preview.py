"""Private upload parsing, transient previews and no provider/business writes."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from portfolios.holdings_csv import MAX_CSV_BYTES
from tests.test_holdings_csv import HEADER, VALID, upload


class HoldingsPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = get_user_model().objects.create_user("holdings-alice")
        cls.bob = get_user_model().objects.create_user("holdings-bob")

    def setUp(self):
        self.client.force_login(self.alice)
        self.url = reverse("holdings_preview")

    def post(self, client=None, content=VALID, **changes):
        return (client or self.client).post(
            self.url,
            {
                "name": "Alice snapshot input",
                "cash": "0",
                "as_of": "2020-01-02",
                "holdings_file": upload(content),
                **changes,
            },
        )

    def test_preview_reads_no_business_tables_writes_no_holdings_and_calls_no_provider(self):
        with (
            patch("httpx.Client.send", side_effect=AssertionError("Unexpected provider call")),
            CaptureQueriesContext(connection) as queries,
        ):
            response = self.post()
        self.assertContains(response, "Input preview — not saved")
        self.assertContains(response, "1.000001")
        self.assertIn("no-store", response.headers["Cache-Control"])
        for query in queries:
            self.assertNotRegex(query["sql"], r"(?i)(portfolios_|ledger_|watchlists_|operations_)")
        self.assertNotIn("Alice snapshot input", str(dict(self.client.session)))
        self.assertNotIn("TSTF", str(dict(self.client.session)))

    def test_get_query_flags_never_supply_a_preview(self):
        response = self.client.get(self.url, {"name": "Injected", "cash": "100", "load": "1"})
        self.assertContains(response, "Check holdings CSV")
        self.assertIsNone(response.context["preview"])
        self.assertFalse(response.context["form"].is_bound)

    def test_second_user_and_reload_cannot_recover_previous_inputs(self):
        self.post()
        for who in (self.alice, self.bob):
            self.client.force_login(who)
            response = self.client.get(self.url)
            self.assertNotContains(response, "Alice snapshot input")
            self.assertIsNone(response.context["preview"])

    def test_anonymous_and_inactive_users_cannot_preview(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"/sign-in/?next={self.url}")
        self.assertEqual(self.post().status_code, 302)
        self.alice.is_active = False
        self.alice.save(update_fields=["is_active"])
        self.client.force_login(self.alice)
        self.assertEqual(self.post().status_code, 302)

    def test_csrf_is_enforced_and_valid_token_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.alice)
        response = self.post(client=client)
        self.assertEqual(response.status_code, 403)
        self.assertIn("no-store", response.headers["Cache-Control"])
        client.get(self.url)
        self.assertContains(
            self.post(client=client, csrfmiddlewaretoken=client.cookies["csrftoken"].value),
            "Input preview — not saved",
        )

    def test_unsafe_methods_are_rejected_with_private_headers(self):
        for method in ("put", "delete", "patch", "head"):
            response = getattr(self.client, method)(self.url)
            self.assertEqual(response.status_code, 405)
            self.assertIn("no-store", response.headers["Cache-Control"])

    def test_invalid_rows_show_all_errors_without_accepted_subset(self):
        response = self.post(content=VALID + b"OTHER,XBAD,0,EUR\n")
        self.assertContains(response, "Row 3")
        self.assertContains(response, "Exchange MIC")
        self.assertContains(response, "Quantity")
        self.assertContains(response, "Currency")
        self.assertIsNone(response.context["preview"])
        self.assertNotContains(response, "Input preview — not saved")

    def test_untrusted_name_and_ticker_are_escaped(self):
        response = self.post(
            name="<script>alert(1)</script>", content=HEADER + b"<script>,XNAS,1,USD\n"
        )
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=1)
    def test_upload_never_falls_back_to_disk_even_with_tiny_global_memory_threshold(self):
        with patch(
            "django.core.files.uploadhandler.TemporaryFileUploadHandler.new_file",
            side_effect=AssertionError("Temporary upload created"),
        ):
            response = self.post()
            self.assertContains(response, "Input preview — not saved")
            response = self.post(content=b"x" * (3 * 1024 * 1024))
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "16 KiB", status_code=400)
            self.assertIsNone(response.context["preview"])

    def test_byte_boundary_and_multiple_or_unexpected_files_are_rejected(self):
        response = self.post(content=HEADER + b"\n" * (MAX_CSV_BYTES - len(HEADER)), cash="1")
        self.assertContains(response, "Cash-only input")
        response = self.post(content=b"x" * (MAX_CSV_BYTES + 1))
        self.assertEqual(response.status_code, 400)
        response = self.post(holdings_file=[upload(), upload()])
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "exactly one", status_code=400)
        response = self.post(other=SimpleUploadedFile("extra.csv", VALID))
        self.assertEqual(response.status_code, 400)

    def test_unrelated_routes_keep_standard_upload_handlers(self):
        from django.test import RequestFactory

        from portfolios.holdings_uploads import HoldingsUploadMiddleware

        request = RequestFactory().get("/portfolios/create/")
        handlers = request.upload_handlers
        middleware = HoldingsUploadMiddleware(lambda request: request)
        middleware(request)
        self.assertIs(request.upload_handlers, handlers)
        self.assertFalse(hasattr(request, "holdings_upload"))
