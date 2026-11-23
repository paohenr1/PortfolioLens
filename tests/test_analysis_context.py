"""Date preferences follow private portfolios without caching results or confirmations."""

import uuid
from datetime import date, timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore as LegacySessionStore
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from config.session_backend import ANALYSIS_DATES_KEY
from ledger.analysis_context import remember_dates
from ledger.models import Entry
from ledger.performance_forms import PerformanceForm
from ledger.services import append_entry
from market_data.errors import CredentialsMissing
from portfolios.services import create_portfolio
from tests.test_ledger import REFERENCE
from tests.test_ledger_domain import DAY, cash, trade

END = date(2020, 1, 8)


@skipUnless(
    connection.vendor == "postgresql", "Analysis context requires private PostgreSQL storage"
)
class AnalysisContextTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("date-context-owner")
        cls.other = get_user_model().objects.create_user("date-context-other")
        cls.portfolio = create_portfolio(owner=cls.user, name="First portfolio")
        cls.second = create_portfolio(owner=cls.user, name="Second portfolio")
        cls.foreign = create_portfolio(owner=cls.other, name="Foreign secret")
        append_entry(
            user=cls.user,
            portfolio_id=cls.portfolio.pk,
            intent=cash(),
            client_key=uuid.uuid4(),
            client_address="127.0.0.1",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.prices = patch("ledger.valuation_services.market_data.daily_prices").start()
        self.addCleanup(patch.stopall)

    def load(self, start=DAY, end=END):
        return self.client.post(
            reverse("portfolio_overview_load", args=[self.portfolio.pk]),
            {"start_date": start, "end_date": end, "timing_checked": "on"},
        )

    def stored_dates(self):
        return self.client.session[ANALYSIS_DATES_KEY]

    def test_overview_dates_follow_all_analysis_pages_without_prices_or_auto_confirmation(self):
        self.assertEqual(self.load().status_code, 200)
        count = Entry.objects.count()
        for route in ("portfolio_performance", "portfolio_daily_returns", "portfolio_detail"):
            response = self.client.get(reverse(route, args=[self.portfolio.pk]))
            form = response.context["overview_form" if route == "portfolio_detail" else "form"]
            self.assertEqual(form.initial["start_date"], DAY)
            self.assertEqual(form.initial["end_date"], END)
            self.assertFalse(form["timing_checked"].value())
            self.assertFalse(form.is_bound)
        response = self.client.get(reverse("portfolio_valuation", args=[self.portfolio.pk]))
        self.assertEqual(response.context["form"].initial["as_of"], END)
        self.assertFalse(response.context["form"]["share_basis_checked"].value())
        self.assertEqual(Entry.objects.count(), count)
        self.prices.assert_not_called()
        state = self.stored_dates()
        self.assertEqual(
            list(state.values()), [{"start_date": DAY.isoformat(), "end_date": END.isoformat()}]
        )

    def test_changing_valuation_date_keeps_existing_opening_date(self):
        self.load()
        new_end = END + timedelta(days=1)
        self.client.post(
            reverse("portfolio_valuation", args=[self.portfolio.pk]),
            {"as_of": new_end, "share_basis_checked": "on"},
        )
        response = self.client.get(reverse("portfolio_performance", args=[self.portfolio.pk]))
        self.assertEqual(response.context["form"].initial["start_date"], DAY)
        self.assertEqual(response.context["form"].initial["end_date"], new_end)
        self.prices.assert_not_called()

    def test_valuation_only_selection_anchors_suggested_period_to_that_date(self):
        self.client.post(
            reverse("portfolio_valuation", args=[self.portfolio.pk]),
            {"as_of": END, "share_basis_checked": "on"},
        )
        response = self.client.get(reverse("portfolio_performance", args=[self.portfolio.pk]))
        self.assertEqual(response.context["form"].initial["end_date"], END)
        self.assertEqual(response.context["form"].initial["start_date"], END - timedelta(days=30))

    def test_valid_dates_survive_a_provider_failure_without_saving_market_results(self):
        with patch("ledger.services.market_data.security_details", return_value=REFERENCE):
            append_entry(
                user=self.user,
                portfolio_id=self.portfolio.pk,
                intent=trade(),
                client_key=uuid.uuid4(),
                client_address="127.0.0.1",
            )
        self.prices.side_effect = CredentialsMissing()
        self.assertEqual(self.load().status_code, 503)
        response = self.client.get(reverse("portfolio_performance", args=[self.portfolio.pk]))
        self.assertEqual(response.context["form"].initial["start_date"], DAY)
        self.assertEqual(response.context["form"].initial["end_date"], END)

    def test_invalid_submission_does_not_replace_last_valid_dates(self):
        self.load()
        before = self.stored_dates()
        response = self.client.post(
            reverse("portfolio_overview_load", args=[self.portfolio.pk]),
            {"start_date": "2021-01-01", "end_date": "2021-01-10"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stored_dates(), before)
        self.prices.assert_not_called()

    def test_slow_response_cannot_replace_newer_dates_or_another_portfolios_dates(self):
        self.assertEqual(self.load(end=END - timedelta(days=1)).status_code, 200)
        request = RequestFactory().post("/")
        request.COOKIES = {name: value.value for name, value in self.client.cookies.items()}
        request.user = self.user
        newer_end = END + timedelta(days=7)

        def slow_view(request):
            self.assertIn(ANALYSIS_DATES_KEY, request.session)
            form = PerformanceForm({"start_date": DAY, "end_date": END, "timing_checked": "on"})
            self.assertTrue(form.is_valid())
            remember_dates(request, self.portfolio.pk, form)
            self.assertEqual(self.load(end=newer_end).status_code, 200)
            other = self.client.post(
                reverse("portfolio_valuation", args=[self.second.pk]),
                {"as_of": END, "share_basis_checked": "on"},
            )
            self.assertEqual(other.status_code, 200)
            return HttpResponse()

        self.assertEqual(SessionMiddleware(slow_view)(request).status_code, 200)
        state = self.stored_dates()
        self.assertEqual(
            state[f"{self.user.pk}:{self.portfolio.pk}"]["end_date"], newer_end.isoformat()
        )
        self.assertEqual(state[f"{self.user.pk}:{self.second.pk}"]["end_date"], END.isoformat())

    def test_session_rotation_carries_forward_the_newest_dates(self):
        self.assertEqual(self.load().status_code, 200)
        stale_session = self.client.session
        previous_key = stale_session.session_key
        self.assertIn(ANALYSIS_DATES_KEY, stale_session)
        newer_end = END + timedelta(days=7)
        self.assertEqual(self.load(end=newer_end).status_code, 200)

        stale_session.cycle_key()

        self.assertNotEqual(stale_session.session_key, previous_key)
        self.assertFalse(stale_session.exists(previous_key))
        key = f"{self.user.pk}:{self.portfolio.pk}"
        rotated = type(stale_session)(stale_session.session_key)
        self.assertEqual(rotated[ANALYSIS_DATES_KEY][key]["end_date"], newer_end.isoformat())

    def test_legacy_session_dates_survive_first_update(self):
        session = LegacySessionStore(self.client.session.session_key)
        session[ANALYSIS_DATES_KEY] = {
            f"{self.user.pk}:{self.portfolio.pk}": {
                "start_date": DAY.isoformat(),
                "end_date": END.isoformat(),
            }
        }
        session.save()
        newer_end = END + timedelta(days=7)
        response = self.client.post(
            reverse("portfolio_valuation", args=[self.portfolio.pk]),
            {"as_of": newer_end, "share_basis_checked": "on"},
        )
        self.assertEqual(response.status_code, 200)
        state = self.stored_dates()[f"{self.user.pk}:{self.portfolio.pk}"]
        self.assertEqual(state, {"start_date": DAY.isoformat(), "end_date": newer_end.isoformat()})

    def test_dates_stay_separate_for_other_portfolios_and_owners(self):
        self.load()
        response = self.client.get(reverse("portfolio_performance", args=[self.second.pk]))
        self.assertNotEqual(response.context["form"].initial["end_date"], END)
        self.assertEqual(
            self.client.get(reverse("portfolio_performance", args=[self.foreign.pk])).status_code,
            404,
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse("portfolio_performance", args=[self.foreign.pk]))
        self.assertNotEqual(response.context["form"].initial["end_date"], END)
        self.prices.assert_not_called()

    def test_daily_risk_keeps_long_range_visible_with_explanation_instead_of_shortening(self):
        end = date(2020, 5, 1)
        self.assertEqual(self.load(end=end).status_code, 200)
        response = self.client.get(reverse("portfolio_daily_returns", args=[self.portfolio.pk]))
        self.assertEqual(response.context["form"].initial["start_date"], DAY)
        self.assertEqual(response.context["form"].initial["end_date"], end)
        self.assertContains(response, "Your selected dates need adjusting here")
        self.assertTrue(response.context["form"].date_notice)
        self.prices.assert_not_called()
