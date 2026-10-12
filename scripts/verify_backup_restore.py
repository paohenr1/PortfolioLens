"""Create, export and restore only two generated test databases, then remove both."""

import argparse
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.database import database_settings  # noqa: E402
from operations.backups import run_tool  # noqa: E402
from scripts.development_database import ROOT, database_environment  # noqa: E402


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    import psycopg
    from psycopg import sql

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-container", action="store_true")
    local_container = parser.parse_args().local_container
    lease = uuid.uuid4().hex
    source, target = ("test_stock_backup_" + lease + "_" + suffix for suffix in ("a", "b"))
    # Fixed local test role: it cannot connect to development storage. Production
    # restore is deliberately not exposed through this non-destructive drill.
    environ = {
        **os.environ,
        **database_environment("stock_research_test", source),
        "DJANGO_ENV": "development",
        "DJANGO_DEBUG": "true",
        # A restore must use the same separately provisioned application secret
        # to validate sessions. This ephemeral fixture key is never printed/saved.
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "DJANGO_ALLOWED_HOSTS": "127.0.0.1",
        "DJANGO_TRUST_PROXY_HTTPS": "false",
        "DJANGO_RATE_LIMIT_BACKEND": "postgresql",
        "INTRINIO_API_KEY": "",
    }
    configured = database_settings(environ, ROOT, production=False)
    parameters = {
        "host": configured["HOST"],
        "port": configured["PORT"],
        "user": configured["USER"],
        "password": configured["PASSWORD"],
        **configured["OPTIONS"],
    }
    created = []
    signal.signal(signal.SIGTERM, interrupted)
    with psycopg.connect(dbname="postgres", autocommit=True, **parameters) as control:
        try:
            for name in (source, target):
                control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                oid = control.execute(
                    "SELECT oid FROM pg_database WHERE datname=%s", (name,)
                ).fetchone()[0]
                created.append((name, oid))
                control.execute(
                    sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(name)
                    )
                )
            with tempfile.TemporaryDirectory(prefix="stock-backup-drill-") as directory:
                archive, manifest = (
                    Path(directory) / "synthetic.dump",
                    Path(directory) / "manifest.json",
                )
                subprocess.run(
                    [sys.executable, "manage.py", "migrate", "--noinput"],
                    cwd=ROOT,
                    env=environ,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    timeout=30,
                )
                subprocess.run(
                    [sys.executable, "tests/backup_restore_fixture.py", "seed", str(manifest)],
                    cwd=ROOT,
                    env=environ,
                    check=True,
                    timeout=30,
                )
                command = [sys.executable, "manage.py", "backup_database", "--output", str(archive)]
                if local_container:
                    command.append("--local-container")
                subprocess.run(command, cwd=ROOT, env=environ, check=True, timeout=120)
                size = archive.stat().st_size
                with archive.open("rb") as stream:
                    run_tool(
                        {**configured, "NAME": target},
                        "pg_restore",
                        ["--exit-on-error", "--no-owner", "--no-acl", "--dbname=" + target],
                        local_container=local_container,
                        stdin=stream,
                    )
                subprocess.run(
                    [sys.executable, "tests/backup_restore_fixture.py", "verify", str(manifest)],
                    cwd=ROOT,
                    env={**environ, "DJANGO_DATABASE_NAME": target},
                    check=True,
                    timeout=30,
                )
                assert archive.stat().st_mode & 0o777 == 0o600
                print(
                    f"Backup/restore drill PASS ({size} synthetic archive bytes); "
                    "all row digests match."
                )
        finally:
            failures = []
            for name, oid in reversed(created):
                identity = control.execute(
                    "SELECT oid, datdba::regrole::text FROM pg_database WHERE datname=%s", (name,)
                ).fetchone()
                if identity != (oid, "stock_research_test"):
                    failures.append(name)
                    continue
                control.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
            if failures:
                raise RuntimeError(
                    "A drill database changed ownership/identity; it was left untouched."
                )
    print("Owned source/restore databases and temporary synthetic archive removed.")


if __name__ == "__main__":
    main()
