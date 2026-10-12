"""Archive privacy, safe failures and TLS/credential forwarding without a real DB."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from operations.backups import BackupError, export_database, run_tool

CONFIGURED = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "fixture_database",
    "USER": "fixture_user",
    "HOST": "fixture.example.test",
    "PORT": "5432",
    "PASSWORD": "private-fixture-password",
    "OPTIONS": {"sslmode": "verify-full", "sslrootcert": "/fixture/ca.pem"},
}


class BackupSafetyTests(SimpleTestCase):
    def test_existing_files_and_symlinks_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "original.dump"
            existing.write_bytes(b"original")
            symlink = Path(directory) / "link.dump"
            symlink.symlink_to(existing)
            with patch("operations.backups.run_tool") as tool:
                for name in (existing, symlink):
                    with self.assertRaises(BackupError):
                        export_database(CONFIGURED, name)
                tool.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"original")
            self.assertTrue(symlink.is_symlink())

    def test_new_archive_has_private_permissions_and_is_checked_before_success(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "new.dump"
            operations = []

            def tool(configuration, name, arguments, **streams):
                operations.append((name, arguments))
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
                if name == "pg_dump":
                    streams["stdout"].write(b"synthetic-only")
                else:
                    self.assertEqual(streams["stdin"].read(), b"synthetic-only")

            with patch("operations.backups.run_tool", side_effect=tool):
                self.assertEqual(export_database(CONFIGURED, archive), 14)
            self.assertEqual([name for name, _ in operations], ["pg_dump", "pg_restore"])
            self.assertEqual(operations[-1][1], ["--list"])

    def test_partial_archive_is_removed_on_tool_failure_or_interruption(self):
        with tempfile.TemporaryDirectory() as directory:
            for failure in (BackupError("Fixed failure"), KeyboardInterrupt()):
                archive = Path(directory) / "failed.dump"
                with patch("operations.backups.run_tool", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        export_database(CONFIGURED, archive)
                self.assertFalse(archive.exists())

    def test_failure_cleanup_never_removes_a_replacement_file(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "failed.dump"

            def replaced(*args, **kwargs):
                archive.rename(Path(directory) / "partial.dump")
                archive.write_bytes(b"replacement")
                raise BackupError("Fixed failure")

            with patch("operations.backups.run_tool", side_effect=replaced):
                with self.assertRaises(BackupError):
                    export_database(CONFIGURED, archive)
            self.assertEqual(archive.read_bytes(), b"replacement")

    def test_native_password_and_verified_tls_stay_out_of_argv(self):
        with (
            patch.dict(
                "os.environ", {"PGSERVICE": "unselected", "PGOPTIONS": "-c search_path=other"}
            ),
            patch("operations.backups.shutil.which", return_value="/fixture/pg_dump"),
            patch(
                "operations.backups.subprocess.run", return_value=subprocess.CompletedProcess([], 0)
            ) as run,
        ):
            run_tool(CONFIGURED, "pg_dump", ["--format=custom", "--dbname=fixture_database"])
        args, kwargs = run.call_args
        self.assertNotIn(CONFIGURED["PASSWORD"], str(args))
        self.assertEqual(kwargs["env"]["PGPASSWORD"], CONFIGURED["PASSWORD"])
        self.assertEqual(kwargs["env"]["PGSSLMODE"], "verify-full")
        self.assertEqual(kwargs["env"]["PGSSLROOTCERT"], "/fixture/ca.pem")
        self.assertIn("--no-password", args[0])
        self.assertIn("--host=fixture.example.test", args[0])
        self.assertNotIn("PGSERVICE", kwargs["env"])
        self.assertNotIn("PGOPTIONS", kwargs["env"])

    def test_failed_tool_output_is_not_exposed(self):
        with (
            patch("operations.backups.shutil.which", return_value="/fixture/pg_dump"),
            patch(
                "operations.backups.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1, stderr=b"private-fixture-password"),
            ),
        ):
            with self.assertRaises(BackupError) as error:
                run_tool(CONFIGURED, "pg_dump", [])
        self.assertNotIn(CONFIGURED["PASSWORD"], str(error.exception))

    def test_missing_tools_or_non_postgres_configuration_fail_explicitly(self):
        with patch("operations.backups.shutil.which", return_value=None):
            with self.assertRaisesMessage(BackupError, "client tools"):
                run_tool(CONFIGURED, "pg_dump", [])
        with self.assertRaisesMessage(BackupError, "PostgreSQL is required"):
            run_tool({**CONFIGURED, "ENGINE": "django.db.backends.sqlite3"}, "pg_dump", [])

    def test_local_container_connection_cannot_silently_target_another_host(self):
        with self.assertRaisesMessage(BackupError, "private socket"):
            run_tool(CONFIGURED, "pg_dump", [], local_container=True)
