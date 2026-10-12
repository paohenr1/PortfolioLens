"""Independent covariance/slope examples and exact-factor integration checks."""

import subprocess
import sys
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction

from django.test import SimpleTestCase

from ledger.benchmarks import calculate_comparison
from ledger.relationships import calculate_relationship
from tests.test_benchmarks import BENCHMARK_ID, BENCHMARK_REFERENCE, benchmark_history
from tests.test_risk import fixture_series

D = Decimal
F = Fraction


def factors(returns, repeats=5):
    return tuple(1 + F(value) for value in returns) * repeats


class RelationshipCalculationTests(SimpleTestCase):
    def test_equal_direction_and_twice_sensitivity(self):
        result = calculate_relationship(
            factors(["0.02", "0.04", "0.06", "0.08"]), factors(["0.01", "0.02", "0.03", "0.04"])
        )
        self.assertEqual(result.correlation, D(1))
        self.assertEqual(result.beta, D(2))
        self.assertEqual(result.observations, 20)

    def test_opposite_direction_can_have_negative_beta(self):
        result = calculate_relationship(
            factors(["-0.02", "-0.04", "-0.06", "-0.08"]), factors(["0.01", "0.02", "0.03", "0.04"])
        )
        self.assertEqual(result.correlation, D(-1))
        self.assertEqual(result.beta, D(-2))

    def test_beta_centers_returns_and_fits_an_intercept(self):
        benchmark = factors(["0.01", "0.02", "0.03", "0.04"])
        portfolio = tuple(1 + F("0.05") + (value - 1) * F("0.4") for value in benchmark)
        result = calculate_relationship(portfolio, benchmark)
        self.assertEqual(result.beta, D("0.4"))
        self.assertEqual(result.correlation, D(1))

    def test_hand_calculated_partial_correlation_and_beta(self):
        result = calculate_relationship(
            factors(["0", "0.01", "0.02", "0.03"]), factors(["0", "0.01", "0.03", "0.02"])
        )
        # Centered integer-scaled cross products total 4; each sum of squares is 5.
        self.assertEqual(result.correlation, D("0.8"))
        self.assertEqual(result.beta, D("0.8"))

    def test_irrational_correlation_rounds_only_at_final_display(self):
        result = calculate_relationship(
            factors(["0", "0.01", "0", "0.01"]), factors(["0", "0", "0", "0.01"])
        )
        self.assertEqual(result.correlation, D("0.5774"))  # 1 / sqrt(3)
        self.assertEqual(result.beta, D("0.6667"))  # 2 / 3

    def test_orthogonal_varying_returns_have_zero_correlation_and_beta(self):
        result = calculate_relationship(
            factors(["0", "0.01", "0", "-0.01"]), factors(["0.01", "0", "-0.01", "0"])
        )
        self.assertEqual(result.correlation, D(0))
        self.assertEqual(result.beta, D(0))

    def test_constant_portfolio_has_zero_beta_and_undefined_correlation(self):
        result = calculate_relationship(
            (F("1.01"),) * 20, factors(["0.01", "0.02", "0.03", "0.04"])
        )
        self.assertEqual(result.beta, D(0))
        self.assertIsNone(result.correlation)
        self.assertIsNone(result.issue)
        self.assertIn("Portfolio return variance is zero", result.correlation_issue)

    def test_constant_benchmark_withholds_both_coefficients(self):
        result = calculate_relationship(factors(["0.01", "0.02", "0.03", "0.04"]), (F(1),) * 20)
        self.assertIsNone(result.beta)
        self.assertIsNone(result.correlation)
        self.assertIn("Benchmark return variance is zero", result.issue)

    def test_both_constant_series_have_no_defined_relationship(self):
        result = calculate_relationship((F(1),) * 20, (F(1),) * 20)
        self.assertIsNone(result.beta)
        self.assertIsNone(result.correlation)

    def test_nineteen_returns_do_not_satisfy_minimum(self):
        values = factors(["0", "0.01", "0.02", "0.03"])[:19]
        result = calculate_relationship(values, values)
        self.assertEqual(result.observations, 19)
        self.assertIsNone(result.beta)
        self.assertIn("twenty", result.issue)

    def test_exactly_twenty_returns_enable_both(self):
        values = factors(["0", "0.01", "0.02", "0.03"])
        result = calculate_relationship(values, values)
        self.assertEqual(result.correlation, D(1))
        self.assertEqual(result.beta, D(1))

    def test_mismatched_lengths_cannot_be_zipped_or_dropped(self):
        values = factors(["0", "0.01", "0.02", "0.03"])
        result = calculate_relationship(values, values[:-1])
        self.assertEqual(result.observations, 0)
        self.assertIsNone(result.beta)

    def test_invalid_unbounded_or_rounded_inputs_fail_closed(self):
        valid = factors(["0", "0.01", "0.02", "0.03"])
        variants = (
            (),
            list(valid),
            valid * 5,
            (None, *valid[1:]),
            (D("NaN"), *valid[1:]),
            (D("1.01"), *valid[1:]),
            (F(-1), *valid[1:]),
            (F(10**31), *valid[1:]),
            (F(1, 2**201), *valid[1:]),
        )
        for values in variants:
            with self.subTest(values=values):
                result = calculate_relationship(values, valid)
                self.assertIsNone(result.beta)
                self.assertEqual(result.observations, 0)

    def test_tiny_exact_variation_is_not_mistaken_for_zero(self):
        benchmark = tuple(1 + F(value, 10**30) for value in (1, 2, 3, 4)) * 5
        portfolio = tuple(1 + 2 * (value - 1) for value in benchmark)
        result = calculate_relationship(portfolio, benchmark)
        self.assertEqual(result.correlation, D(1))
        self.assertEqual(result.beta, D(2))

    def test_beta_half_ties_round_away_from_zero_without_double_rounding(self):
        benchmark = factors(["0", "0.001", "0.002", "0.003"])
        tie = F(40001, 20000)
        for slope, expected in (
            (tie, D("2.0001")),
            (-tie, D("-2.0001")),
            (tie - F(1, 10**40), D("2.0000")),
            (-tie + F(1, 10**40), D("-2.0000")),
        ):
            with self.subTest(slope=slope):
                portfolio = tuple(1 + slope * (value - 1) for value in benchmark)
                self.assertEqual(calculate_relationship(portfolio, benchmark).beta, expected)

    def test_coefficients_are_invariant_to_return_units_and_repeating_sample(self):
        portfolio = factors(["0", "0.01", "0.02", "0.03"])
        benchmark = factors(["0", "0.01", "0.03", "0.02"])
        expected = calculate_relationship(portfolio, benchmark)
        scaled_portfolio = tuple(1 + (value - 1) * 10 for value in portfolio)
        scaled_benchmark = tuple(1 + (value - 1) * 10 for value in benchmark)
        actual = calculate_relationship(scaled_portfolio * 2, scaled_benchmark * 2)
        self.assertEqual(actual.beta, expected.beta)
        self.assertEqual(actual.correlation, expected.correlation)

    def test_caller_precision_exponent_limits_and_inexact_traps_do_not_change_result(self):
        values = factors(["0", "0.01", "0.02", "0.03"])
        benchmark = factors(["0", "0.01", "0.03", "0.02"])
        expected = calculate_relationship(values, benchmark)
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 1, 1, -1
            context.traps[Inexact] = True
            self.assertEqual(calculate_relationship(values, benchmark), expected)

    def test_terminal_total_loss_is_an_observation_not_a_dropped_row(self):
        values = factors(["0", "0.01", "0.02", "0.03"])[:-1] + (F(0),)
        result = calculate_relationship(values, values)
        self.assertEqual(result.observations, 20)
        self.assertEqual(result.beta, D(1))
        self.assertEqual(result.correlation, D(1))

    def test_coefficients_have_four_places_and_no_negative_zero(self):
        result = calculate_relationship(
            factors(["0", "0.01", "0", "-0.01"]), factors(["0.01", "0", "-0.01", "0"])
        )
        self.assertEqual(str(result.beta), "0.0000")
        self.assertEqual(str(result.correlation), "0.0000")

    def test_import_needs_no_django_database_or_http_client(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import ledger.relationships; "
                "assert 'django' not in sys.modules; assert 'httpx' not in sys.modules",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class RelationshipComparisonTests(SimpleTestCase):
    def test_comparison_uses_exact_factors_when_displayed_returns_are_zero(self):
        series = fixture_series(["100000000", "100000002"] * 10 + ["100000000"])
        history = benchmark_history(series, ["50", "50.0000005"] * 10 + ["50"])
        result = calculate_comparison(series, BENCHMARK_REFERENCE, history, BENCHMARK_ID)
        self.assertTrue(
            all(
                row.portfolio_return_percent == row.benchmark_return_percent == 0
                for row in result.rows
            )
        )
        self.assertEqual(result.relationship.observations, 20)
        self.assertEqual(result.relationship.correlation, D(1))
        self.assertEqual(result.relationship.beta, D(2))

    def test_missing_middle_price_withholds_relationship_and_comparison(self):
        series = fixture_series(["100", "101"] * 10 + ["100"])
        history = benchmark_history(series)
        history = replace(
            history, observations=history.observations[:10] + history.observations[11:]
        )
        result = calculate_comparison(series, BENCHMARK_REFERENCE, history, BENCHMARK_ID)
        self.assertIsNone(result.relationship.beta)
        self.assertIsNone(result.relationship.correlation)
        self.assertEqual(result.relationship.observations, 0)

    def test_inconsistent_portfolio_metadata_does_not_create_statistics(self):
        series = fixture_series(["100", "101"] * 10 + ["100"])
        result = calculate_comparison(
            replace(series, return_percent=D(999)),
            BENCHMARK_REFERENCE,
            benchmark_history(series),
            BENCHMARK_ID,
        )
        self.assertIsNone(result.relationship.beta)
        self.assertEqual(result.relationship.observations, 0)

    def test_short_complete_comparison_still_has_returns_and_a_sample_explanation(self):
        series = fixture_series(["100", "110"])
        result = calculate_comparison(
            series, BENCHMARK_REFERENCE, benchmark_history(series, ["50", "55"]), BENCHMARK_ID
        )
        self.assertEqual(result.difference_points, D(0))
        self.assertEqual(result.relationship.observations, 1)
        self.assertIsNone(result.relationship.correlation)
        self.assertIn("twenty", result.relationship.issue)
