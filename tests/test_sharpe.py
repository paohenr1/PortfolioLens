"""Independent Sharpe examples, explicit-rate validation and complete-series gates."""

import subprocess
import sys
from dataclasses import replace
from decimal import Decimal, localcontext

from django.test import SimpleTestCase

from ledger.daily_return_forms import DailyReturnForm
from ledger.performance import Performance
from ledger.sharpe import calculate_sharpe
from tests.test_risk import fixture_series

D = Decimal


class SharpeCalculationTests(SimpleTestCase):
    def setUp(self):
        self.series = fixture_series(["100", "200"] * 10 + ["100"])

    def test_hand_calculated_sample_daily_and_annualized_sharpe(self):
        # Ten +100% and ten -50% returns: mean 1/4, sample variance 11.25/19.
        # Daily squared Sharpe = 19/180; annualized squared Sharpe = 26.6.
        result = calculate_sharpe(self.series, D(0))
        self.assertEqual(result.observations, 20)
        self.assertEqual(result.mean_excess_percent, D(25))
        self.assertEqual(result.daily_sharpe, D("0.3249"))
        self.assertEqual(result.annualized_sharpe, D("5.1575"))

    def test_explicit_rate_is_annual_simple_divided_by_252(self):
        result = calculate_sharpe(self.series, D(4))
        self.assertEqual(result.daily_risk_free_percent, D("0.0159"))
        self.assertEqual(result.mean_excess_percent, D("24.9841"))
        self.assertEqual(result.daily_sharpe, D("0.3247"))
        self.assertEqual(result.annualized_sharpe, D("5.1542"))

    def test_annualization_uses_unrounded_ratio_not_displayed_daily_sharpe(self):
        result = calculate_sharpe(self.series, D(0))
        with localcontext() as context:
            context.prec = 40
            incorrect = (result.daily_sharpe * D(252).sqrt()).quantize(D("0.0001"))
        self.assertNotEqual(result.annualized_sharpe, incorrect)

    def test_negative_mean_excess_gives_negative_ratios(self):
        series = fixture_series(["100", "90"] * 10 + ["90"])
        result = calculate_sharpe(series, D(100))
        self.assertLess(result.mean_excess_percent, D(0))
        self.assertLess(result.daily_sharpe, D(0))
        self.assertLess(result.annualized_sharpe, D(0))

    def test_negative_rate_is_an_explicit_supported_assumption(self):
        negative = calculate_sharpe(self.series, D(-4))
        zero = calculate_sharpe(self.series, D(0))
        self.assertGreater(negative.daily_sharpe, zero.daily_sharpe)
        self.assertEqual(negative.daily_risk_free_percent, D("-0.0159"))

    def test_zero_mean_with_nonzero_volatility_is_a_valid_zero_ratio(self):
        series = fixture_series(["100", "90"] * 10 + ["90"])
        result = calculate_sharpe(series, D(0))
        self.assertIsNone(result.issue)
        self.assertEqual(str(result.daily_sharpe), "0.0000")
        self.assertEqual(str(result.annualized_sharpe), "0.0000")

    def test_zero_volatility_is_undefined_even_with_positive_or_negative_excess(self):
        series = fixture_series(["100"] * 21)
        for rate in (D(0), D(4), D(-4)):
            result = calculate_sharpe(series, rate)
            self.assertIsNone(result.daily_sharpe)
            self.assertIsNone(result.annualized_sharpe)
            self.assertIn("volatility is zero", result.issue)

    def test_nineteen_complete_returns_withhold_both_ratios(self):
        series = fixture_series(["100", "200"] * 10)
        result = calculate_sharpe(series, D(0))
        self.assertEqual(result.observations, 19)
        self.assertIsNone(result.daily_sharpe)
        self.assertIn("twenty", result.issue)

    def test_incomplete_or_inconsistent_series_cannot_be_reduced_to_valid_rows(self):
        for series in (
            replace(self.series, issue="Missing quote"),
            replace(self.series, return_percent=D(999)),
            replace(self.series, periods=self.series.periods[:-1]),
        ):
            result = calculate_sharpe(series, D(0))
            self.assertIsNone(result.daily_sharpe)
            self.assertEqual(result.observations, 0)

    def test_plain_cash_flow_boundary_performance_is_not_daily_data(self):
        ordinary = Performance(
            self.series.start_date,
            self.series.end_date,
            self.series.periods,
            self.series.return_percent,
            None,
        )
        self.assertIsNone(calculate_sharpe(ordinary, D(0)).daily_sharpe)

    def test_missing_nonfinite_unbounded_or_overprecise_rate_is_not_assumed_zero(self):
        for rate in (
            None,
            0,
            "0",
            D("NaN"),
            D("sNaN"),
            D("Infinity"),
            D(101),
            D(-101),
            D("0.00001"),
            D("0e999999"),
        ):
            with self.subTest(rate=rate):
                result = calculate_sharpe(self.series, rate)
                self.assertIsNone(result.annual_risk_free_percent)
                self.assertIsNone(result.daily_sharpe)

    def test_caller_decimal_precision_does_not_change_results(self):
        expected = calculate_sharpe(self.series, D(4))
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(calculate_sharpe(self.series, D(4)), expected)

    def test_tiny_variation_that_displays_as_zero_still_defines_sharpe(self):
        series = fixture_series(["100000000", "100000002"] * 10 + ["100000000"])
        result = calculate_sharpe(series, D(0))
        self.assertIsNone(result.issue)
        self.assertIsNotNone(result.daily_sharpe)

    def test_complete_terminal_total_loss_is_kept_as_an_observation(self):
        series = fixture_series(["100", "200"] * 10 + ["0"])
        result = calculate_sharpe(series, D(0))
        self.assertEqual(result.observations, 20)
        self.assertIsNone(result.issue)

    def test_external_funding_is_removed_before_excess_return_calculation(self):
        values = ["100", "200"] * 10 + ["100"]
        flows = ["0"] * 21
        flows[-1] = "50"
        funded = fixture_series(values[:-1] + ["150"], flows)
        self.assertEqual(calculate_sharpe(funded, D(4)), calculate_sharpe(self.series, D(4)))

    def test_pure_import_needs_no_django_or_http_library(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import ledger.sharpe; assert 'django' not in sys.modules; "
                "assert 'httpx' not in sys.modules",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class SharpeFormTests(SimpleTestCase):
    def form(self, **changes):
        return DailyReturnForm(
            {
                "start_date": "2020-01-02",
                "end_date": "2020-01-31",
                "timing_checked": "on",
                **changes,
            }
        )

    def test_blank_assumption_preserves_existing_workflow(self):
        form = self.form()
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data["annual_risk_free_percent"])

    def test_explicit_zero_requires_confirmation(self):
        form = self.form(annual_risk_free_percent="0")
        self.assertFalse(form.is_valid())
        self.assertIn("sharpe_assumption_checked", form.errors)

    def test_zero_and_negative_rate_can_be_explicitly_confirmed(self):
        for rate in ("0", "-4", "100", "-100", "4.1234"):
            form = self.form(annual_risk_free_percent=rate, sharpe_assumption_checked="on")
            self.assertTrue(form.is_valid(), form.errors)

    def test_confirmation_without_rate_does_not_invent_a_value(self):
        form = self.form(sharpe_assumption_checked="on")
        self.assertFalse(form.is_valid())
        self.assertIn("annual_risk_free_percent", form.errors)

    def test_malformed_extreme_and_overprecise_rates_are_rejected(self):
        for rate in ("NaN", "Infinity", "101", "-101", "1e999999", "0.00001", "bad"):
            self.assertFalse(
                self.form(annual_risk_free_percent=rate, sharpe_assumption_checked="on").is_valid()
            )

    def test_unbound_form_has_no_default_risk_free_assumption(self):
        self.assertNotIn("annual_risk_free_percent", DailyReturnForm().initial)
