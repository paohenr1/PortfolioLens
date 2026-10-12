"""Database configuration must fail closed without echoing credentials."""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.database import database_settings


class DatabaseSettingsTests(SimpleTestCase):
    def configured(self, **values):
        return {
            "DJANGO_DATABASE_ENGINE": "postgresql",
            "DJANGO_DATABASE_NAME": "fixture_database",
            "DJANGO_DATABASE_USER": "fixture_user",
            "DJANGO_DATABASE_HOST": "db.fixture.example",
            **values,
        }

    def load(self, values, production=False):
        return database_settings(values, Path("/tmp/project"), production=production)

    def test_development_defaults_to_sqlite_for_research_accounts(self):
        self.assertEqual(self.load({})["ENGINE"], "django.db.backends.sqlite3")

    def test_production_cannot_use_sqlite(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "Production requires"):
            self.load({}, production=True)

    def test_postgres_options_do_not_silently_use_sqlite(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "require"):
            self.load({"DJANGO_DATABASE_HOST": "db.fixture.example"})

    def test_unknown_engine_does_not_echo_value(self):
        with self.assertRaises(ImproperlyConfigured) as error:
            self.load({"DJANGO_DATABASE_ENGINE": "private-fixture-value"})
        self.assertNotIn("private-fixture-value", str(error.exception))

    def test_postgresql_requires_explicit_name_user_host(self):
        for name in ("NAME", "USER", "HOST"):
            with self.subTest(name=name):
                values = self.configured()
                values.pop(f"DJANGO_DATABASE_{name}")
                with self.assertRaisesMessage(ImproperlyConfigured, f"DJANGO_DATABASE_{name}"):
                    self.load(values)

    def test_identifiers_host_port_and_tls_are_validated(self):
        for name, value in (
            ("NAME", "database;DROP TABLE users"),
            ("USER", "bad user"),
            ("HOST", "https://db.example"),
            ("HOST", "/tmp/../private"),
            ("HOST", "/" + "x" * 110),
            ("PORT", "0"),
            ("PORT", "65536"),
            ("PORT", "١٢٣"),
            ("SSLMODE", "prefer"),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ImproperlyConfigured) as error:
                    self.load(self.configured(**{f"DJANGO_DATABASE_{name}": value}))
                self.assertNotIn(value, str(error.exception))

    def test_private_local_socket_is_supported_in_development(self):
        settings = self.load(self.configured(DJANGO_DATABASE_HOST="/tmp/private/socket"))
        self.assertEqual(settings["HOST"], "/tmp/private/socket")
        self.assertEqual(settings["PASSWORD"], "")
        self.assertEqual(settings["OPTIONS"]["connect_timeout"], 5)

    def test_production_requires_password_and_verified_tcp_tls(self):
        for values in (
            self.configured(),
            self.configured(
                DJANGO_DATABASE_PASSWORD="fixture-password", DJANGO_DATABASE_SSLMODE="require"
            ),
            self.configured(
                DJANGO_DATABASE_PASSWORD="fixture-password", DJANGO_DATABASE_HOST="/tmp/socket"
            ),
        ):
            with self.assertRaises(ImproperlyConfigured) as error:
                self.load(values, production=True)
            self.assertNotIn("fixture-password", str(error.exception))

    def test_production_tls_configuration_keeps_password_and_certificate_separate(self):
        settings = self.load(
            self.configured(
                DJANGO_DATABASE_PASSWORD="fixture-password",
                DJANGO_DATABASE_SSLROOTCERT="/tmp/ca.crt",
            ),
            production=True,
        )
        self.assertEqual(settings["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(settings["OPTIONS"]["sslrootcert"], "/tmp/ca.crt")
        self.assertNotIn("fixture-password", repr(settings["OPTIONS"]))
