"""A bounded, explicit-period statement check; no raw responses or keys logged."""

from datetime import UTC, datetime

from django.core.management.base import BaseCommand, CommandError

from market_data.errors import ProviderError
from market_data.fundamentals import PERIODS, STATEMENTS
from research.forms import SearchForm, StatementForm
from research.services import company_statement, search_securities


class Command(BaseCommand):
    help = (
        "Verify one standardized statement and fiscal period "
        "(not forecasts or point-in-time history)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--query", default="AAPL")
        parser.add_argument(
            "--statement-code", choices=list(STATEMENTS), default="income_statement"
        )
        parser.add_argument("--fiscal-year", type=int, default=datetime.now(UTC).year - 1)
        parser.add_argument("--fiscal-period", choices=list(PERIODS), default="FY")

    def handle(self, *args, **options):
        query = SearchForm({"q": options["query"]})
        form = StatementForm(
            {field: options[field] for field in ("statement_code", "fiscal_year", "fiscal_period")}
        )
        if not query.is_valid() or not form.is_valid():
            raise CommandError(
                "Provide a valid query, statement, fiscal year, and FY/Q1–Q4 period."
            )
        try:
            result = search_securities(query.cleaned_data["q"], "fundamentals-verification")
            if not result.securities:
                raise CommandError(
                    "No selectable instrument; statement access could not be verified."
                )
            statement = company_statement(
                result.securities[0].id,
                form.cleaned_data["statement_code"],
                form.cleaned_data["fiscal_year"],
                form.cleaned_data["fiscal_period"],
                "fundamentals-verification",
            )
        except ProviderError as error:
            raise CommandError(error.message) from None
        usable = sum(value.value is not None for value in statement.values)
        if not statement.pagination_complete or not usable:
            raise CommandError(
                "Usable statement values with no indicated continuation are required."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Standardized statement access verified: {usable} supplied numeric observations "
                f"for {form.cleaned_data['fiscal_year']} {form.cleaned_data['fiscal_period']}. "
                "Forecasts, point-in-time history, wider coverage, quotas, "
                "and licensing remain unverified."
            )
        )
