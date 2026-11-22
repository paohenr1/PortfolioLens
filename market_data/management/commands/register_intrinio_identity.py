"""Register one verified listing, including the issuer when Intrinio supplies it."""

from django.core.management.base import BaseCommand, CommandError

from market_data.errors import ProviderError
from market_data.fields import valid_provider_id
from market_data.identities import register_intrinio_instrument
from research.services import security_details


class Command(BaseCommand):
    help = "Register or enrich one local instrument identity using Intrinio reference data."

    def add_arguments(self, parser):
        parser.add_argument("security_id")

    def handle(self, *args, **options):
        security_id = options["security_id"]
        if not valid_provider_id(security_id):
            raise CommandError("Enter a valid Intrinio security ID.")
        try:
            security = security_details(security_id, "identity-registration").security
        except ProviderError as error:
            raise CommandError(error.message) from None
        if security.id != security_id:
            raise CommandError("Intrinio returned a different security ID.")
        local_id = register_intrinio_instrument(security.id, security.company_id)
        self.stdout.write(str(local_id))
