"""Private, exclusive PostgreSQL archives; never overwrite or restore an app DB."""

import json
import os
import shutil
import subprocess
from pathlib import Path


class BackupError(Exception):
    """Fixed operational messages; database/tool details may contain secrets."""


def _local_command(configuration, tool, interactive):
    from scripts.development_database import CONTAINER, IMAGE, LABEL, ROOT, STATE, docker

    if configuration["HOST"] != str(STATE / "socket"):
        raise BackupError("Local-container backups require this checkout's private socket.")
    inspection = docker(
        "container",
        "inspect",
        CONTAINER,
        "--format",
        "{{json .Config.Labels}}|{{json .Mounts}}|{{.State.Running}}|{{.Config.Image}}|"
        "{{.HostConfig.NetworkMode}}|{{.Config.User}}|{{json .HostConfig.PortBindings}}",
        check=False,
    )
    try:
        labels, mounts, running, image, network, user, ports = inspection.stdout.strip().split("|")
        expected = {
            (str(STATE / "data"), "/var/lib/postgresql/data"),
            (str(STATE / "socket"), "/var/run/postgresql"),
        }
        actual = {(mount["Source"], mount["Destination"]) for mount in json.loads(mounts)}
        valid = (
            inspection.returncode == 0
            and json.loads(labels).get(LABEL) == str(ROOT)
            and actual == expected
            and running == "true"
            and image == IMAGE
            and network == "none"
            and user == f"{os.getuid()}:{os.getgid()}"
            and not json.loads(ports)
            and not configuration.get("PASSWORD")
        )
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise BackupError("The managed local database container could not be verified.")
    command = ["docker", "--host=unix:///var/run/docker.sock", "exec"]
    if interactive:
        command.append("-i")
    return [
        *command,
        CONTAINER,
        tool,
        "--host=/var/run/postgresql",
        "--username=" + configuration["USER"],
    ]


def run_tool(configuration, tool, arguments, *, local_container=False, stdin=None, stdout=None):
    if configuration["ENGINE"] != "django.db.backends.postgresql":
        raise BackupError("PostgreSQL is required for database archives.")
    if tool not in {"pg_dump", "pg_restore"}:
        raise BackupError("Unsupported archive tool.")
    environ = os.environ.copy()
    if local_container:
        command = _local_command(configuration, tool, stdin is not None)
        for name in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            environ.pop(name, None)
    else:
        executable = shutil.which(tool)
        if executable is None:
            raise BackupError("Install PostgreSQL client tools matching the server major version.")
        # A libpq service profile must not redirect the configured destination or
        # override verify-full TLS. Other runtime/proxy/CA settings are preserved.
        for name in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
            environ.pop(name, None)
        command = [
            executable,
            "--host=" + configuration["HOST"],
            "--port=" + str(configuration["PORT"]),
            "--username=" + configuration["USER"],
        ]
        # The password remains in the child's environment, never argv or an archive.
        environ.update(
            PGHOST=configuration["HOST"],
            PGPORT=str(configuration["PORT"]),
            PGUSER=configuration["USER"],
            PGPASSWORD=configuration["PASSWORD"],
            PGCONNECT_TIMEOUT="5",
            PGSSLMODE=configuration["OPTIONS"]["sslmode"],
            PGAPPNAME="stock_research_backup",
            PGSSLROOTCERT=configuration["OPTIONS"].get("sslrootcert", ""),
        )
    # Archive listing takes no connection arguments; the local command's host/user
    # selectors are accepted by pg_restore and do not cause a connection for --list.
    try:
        result = subprocess.run(
            [*command, "--no-password", *arguments],
            env=environ,
            stdin=stdin,
            stdout=stdout if stdout is not None else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("The PostgreSQL archive operation did not complete.") from None
    if result.returncode != 0:
        raise BackupError("The PostgreSQL archive operation failed; details are not displayed.")


def export_database(configuration, output, *, local_container=False):
    """pg_dump consistent custom snapshot; refuse existing files and symlinks."""
    path = Path(output)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise BackupError(
            "Choose a new archive filename in an existing private directory."
        ) from None
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as archive:
            run_tool(
                configuration,
                "pg_dump",
                ["--format=custom", "--no-owner", "--no-acl", "--dbname=" + configuration["NAME"]],
                local_container=local_container,
                stdout=archive,
            )
            archive.flush()
            os.fsync(archive.fileno())
        with path.open("rb") as archive:
            run_tool(
                configuration,
                "pg_restore",
                ["--list"],
                local_container=local_container,
                stdin=archive,
            )
    except BaseException:
        # Remove only the partial file created by this invocation, never a replacement.
        try:
            current = path.lstat()
        except FileNotFoundError:
            current = None
        if current and (current.st_ino, current.st_dev) == (identity.st_ino, identity.st_dev):
            path.unlink()
        raise
    return path.stat().st_size
