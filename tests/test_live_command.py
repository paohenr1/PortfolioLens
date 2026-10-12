from io import StringIO
from unittest.mock import patch

import httpx
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from market_data.intrinio import IntrinioClient
from research.services import _request_budget
from tests.test_intrinio import TEST_KEY, fixture


class LiveCommandTests(SimpleTestCase):
    def setUp(self):
        _request_budget.reset()
        self.addCleanup(_request_budget.reset)

    @override_settings(INTRINIO_API_KEY="")
    def test_missing_key_fails_instead_of_reporting_live_success(self):
        with patch("research.services.IntrinioClient") as provider:
            with self.assertRaisesMessage(CommandError, "Intrinio is not configured"):
                call_command("verify_intrinio", stdout=StringIO())
        provider.assert_not_called()

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_mocked_verification_uses_two_requests_and_does_not_claim_price_access(self):
        requests = []

        def handler(request):
            requests.append(request)
            name = (
                "security_search.json"
                if request.url.path.endswith("search")
                else "security_reference.json"
            )
            return httpx.Response(200, json=fixture(name))

        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(key, transport=httpx.MockTransport(handler)),
        ):
            output = StringIO()
            call_command("verify_intrinio", stdout=output)
        self.assertEqual(len(requests), 2)
        self.assertIn("Price and fundamentals access has not been verified", output.getvalue())
        self.assertNotIn(TEST_KEY, output.getvalue())

    @override_settings(INTRINIO_API_KEY=TEST_KEY)
    def test_empty_results_do_not_complete_live_selection_verification(self):
        with patch(
            "research.services.IntrinioClient",
            side_effect=lambda key: IntrinioClient(
                key,
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"securities": []})
                ),
            ),
        ):
            with self.assertRaisesMessage(CommandError, "selection could not be verified"):
                call_command("verify_intrinio", stdout=StringIO())
