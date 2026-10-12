"""Two bounded live reference requests; no raw responses or credentials printed."""

from django.core.management.base import BaseCommand, CommandError

from market_data.errors import ProviderError
from research.forms import SearchForm
from research.services import search_securities, security_details


class Command(BaseCommand):
    help = "Verify live Intrinio search and reference access (not prices or fundamentals)."

    def add_arguments(self, parser):
        parser.add_argument("--query", default="AAPL", help="Ticker or company-name search query.")

    def handle(self, *args, **options):
        form = SearchForm({"q": options["query"]})
        if not form.is_valid():
            raise CommandError("Provide a valid ticker or company name of 1 to 100 characters.")
        try:
            result = search_securities(form.cleaned_data["q"], "management-command")
            if not result.securities:
                raise CommandError(
                    "Search responded without matches; instrument selection could not be verified."
                )
            security_details(result.securities[0].id, "management-command")
        except ProviderError as error:
            raise CommandError(error.message) from None
        self.stdout.write(
            self.style.SUCCESS(
                "Search and instrument-reference requests completed. "
                "Price and fundamentals access has not been verified."
            )
        )
