"""Export only; restores must target a separately created disposable database."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from operations.backups import BackupError, export_database


class Command(BaseCommand):
    help = "Export a private PostgreSQL custom archive to a new file (never overwrite)."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)
        parser.add_argument("--local-container", action="store_true")

    def handle(self, *args, **options):
        try:
            size = export_database(
                settings.DATABASES["default"],
                options["output"],
                local_container=options["local_container"],
            )
        except BackupError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(
            f"Private custom archive created ({size} bytes); restore verification is separate."
        )
