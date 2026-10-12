"""Verify a bounded daily-price workflow without recording credentials or responses."""

from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

from market_data.errors import ProviderError
from research.charts import build_price_chart
from research.forms import PriceHistoryForm, SearchForm
from research.services import historical_prices, search_securities


class Command(BaseCommand):
    help = "Verify historical daily close access (not fundamentals or real-time prices)."

    def add_arguments(self, parser):
        parser.add_argument("--query", default="AAPL")
        parser.add_argument("--start-date")
        parser.add_argument("--end-date")
        parser.add_argument("--basis", choices=["adjusted", "raw"], default="adjusted")

    def handle(self, *args, **options):
        today = datetime.now(UTC).date()
        query = SearchForm({"q": options["query"]})
        dates = PriceHistoryForm(
            {
                "start_date": options["start_date"] or (today - timedelta(days=29)).isoformat(),
                "end_date": options["end_date"] or today.isoformat(),
                "basis": options["basis"],
            }
        )
        if not query.is_valid() or not dates.is_valid():
            raise CommandError(
                "Provide a valid query, price basis, and date range of at most 366 days."
            )
        try:
            results = search_securities(query.cleaned_data["q"], "price-verification")
            if not results.securities:
                raise CommandError("No selectable instrument; price access could not be verified.")
            history = historical_prices(
                results.securities[0].id,
                dates.cleaned_data["start_date"],
                dates.cleaned_data["end_date"],
                "price-verification",
            )
        except ProviderError as error:
            raise CommandError(error.message) from None
        chart = build_price_chart(history, dates.cleaned_data["basis"])
        if not history.pagination_complete or not chart.points:
            raise CommandError("Complete pagination and a usable completed close are required.")
        self.stdout.write(
            self.style.SUCCESS(
                f"Historical daily close access verified: {len(chart.points)} completed "
                f"{chart.basis_label.lower()} observations. "
                "Fundamentals, real-time access, wider coverage, and licensing remain unverified."
            )
        )
