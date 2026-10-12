"""Start only this checkout's private local PostgreSQL; never delete its data."""

import json
import os
import subprocess
import time
from pathlib import Path

IMAGE = "postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4"
CONTAINER = "stock-research-postgres-dev"
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".local/postgres"
LABEL = "stock-research.checkout"


def database_environment(user="stock_research", name="stock_research"):
    """Non-secret connection settings for the private socket and local roles."""
    return {
        "DJANGO_DATABASE_ENGINE": "postgresql",
        "DJANGO_DATABASE_NAME": name,
        "DJANGO_DATABASE_USER": user,
        "DJANGO_DATABASE_HOST": str(STATE / "socket"),
        "DJANGO_DATABASE_PORT": "5432",
        "DJANGO_DATABASE_SSLMODE": "disable",
        "DJANGO_DATABASE_PASSWORD": "",
        "DJANGO_DATABASE_SSLROOTCERT": "",
    }


def docker(*args, check=True, input=None):
    # Clear daemon selectors only, preserving registry credentials and proxies.
    environ = os.environ.copy()
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environ.pop(name, None)
    return subprocess.run(
        ["docker", "--host=unix:///var/run/docker.sock", *args],
        env=environ,
        input=input,
        text=True,
        capture_output=True,
        check=check,
        timeout=60,
    )


def start():
    if len(str(STATE / "socket/.s.PGSQL.5432").encode()) > 107:
        raise RuntimeError("Checkout path is too long for the private PostgreSQL socket.")
    docker("info", "--format", "{{.ServerVersion}}")
    if docker("image", "inspect", IMAGE, "--format", "{{.Id}}", check=False).returncode:
        # Docker checks the pinned digest and preserves daemon TLS/proxy policy.
        docker("pull", IMAGE)
    for directory in (ROOT / ".local", STATE, STATE / "data", STATE / "socket"):
        if directory.is_symlink() or not directory.resolve().is_relative_to(ROOT):
            raise RuntimeError("Refusing a symlinked development database directory.")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.stat().st_uid != os.getuid():
            raise RuntimeError("Development database directories must belong to the task user.")
        directory.chmod(0o700)
    marker = STATE / "managed.json"
    if not marker.exists():
        if any((STATE / "data").iterdir()):
            raise RuntimeError("Unrecognized existing database files; no initialization performed.")
        marker.write_text(json.dumps({"image": IMAGE, "checkout": str(ROOT)}))
    elif json.loads(marker.read_text()) != {"image": IMAGE, "checkout": str(ROOT)}:
        raise RuntimeError("Development database metadata does not match this checkout/image.")

    inspection = docker(
        "container",
        "inspect",
        CONTAINER,
        "--format",
        "{{json .Config.Labels}}|{{json .Mounts}}|{{.State.Running}}|{{.Config.Image}}|"
        "{{.HostConfig.NetworkMode}}|{{.Config.User}}|{{json .HostConfig.PortBindings}}",
        check=False,
    )
    uid = f"{os.getuid()}:{os.getgid()}"
    if inspection.returncode == 0:
        labels, mounts, running, image, network, user, ports = inspection.stdout.strip().split("|")
        expected_mounts = {
            (str(STATE / "data"), "/var/lib/postgresql/data"),
            (str(STATE / "socket"), "/var/run/postgresql"),
        }
        actual_mounts = {(mount["Source"], mount["Destination"]) for mount in json.loads(mounts)}
        if (
            json.loads(labels).get(LABEL) != str(ROOT)
            or actual_mounts != expected_mounts
            or image != IMAGE
            or network != "none"
            or user != uid
            or json.loads(ports)
        ):
            raise RuntimeError("A different container uses the development name; left untouched.")
        if running != "true":
            docker("start", CONTAINER)
    else:
        # No host/container TCP networking. Trust is confined to the owner-only
        # Unix socket directory. Never use this authentication mode in production.
        docker(
            "run",
            "--detach",
            "--name",
            CONTAINER,
            "--label",
            f"{LABEL}={ROOT}",
            "--network",
            "none",
            "--user",
            uid,
            "--mount",
            f"type=bind,src={STATE / 'data'},dst=/var/lib/postgresql/data",
            "--mount",
            f"type=bind,src={STATE / 'socket'},dst=/var/run/postgresql",
            "-e",
            "POSTGRES_USER=stock_bootstrap_admin",
            "-e",
            "POSTGRES_DB=stock_research",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_INITDB_ARGS=--auth-local=trust --auth-host=reject",
            IMAGE,
            "postgres",
            "-c",
            "listen_addresses=",
            "-c",
            "unix_socket_permissions=0700",
        )
    for _ in range(40):
        # The entrypoint runs a temporary server during initdb. Wait for the
        # final postgres PID 1, otherwise readiness can race its shutdown.
        process = docker("exec", CONTAINER, "cat", "/proc/1/comm", check=False)
        ready = docker(
            "exec",
            CONTAINER,
            "pg_isready",
            "-h",
            "/var/run/postgresql",
            "-U",
            "stock_bootstrap_admin",
            "-d",
            "stock_research",
            check=False,
        )
        if process.stdout.strip() == "postgres" and ready.returncode == 0:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("Local PostgreSQL did not become ready; no data was removed.")
    # Fixed identifiers and a dedicated cluster; no user-provided SQL is interpolated.
    sql = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stock_research') THEN
    CREATE ROLE stock_research LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stock_research_test') THEN
    CREATE ROLE stock_research_test LOGIN NOSUPERUSER CREATEDB NOCREATEROLE;
  END IF;
END $$;
ALTER DATABASE stock_research OWNER TO stock_research;
REVOKE CONNECT ON DATABASE stock_research FROM PUBLIC;
GRANT CONNECT ON DATABASE stock_research TO stock_research;
"""
    docker(
        "exec",
        "-i",
        CONTAINER,
        "psql",
        "-h",
        "/var/run/postgresql",
        "-U",
        "stock_bootstrap_admin",
        "-d",
        "stock_research",
        "-v",
        "ON_ERROR_STOP=1",
        input=sql,
    )
    for filename, user in (
        ("database.env", "stock_research"),
        ("database-test.env", "stock_research_test"),
    ):
        path = ROOT / ".local" / filename
        if not path.exists():
            name = "stock_research" if user == "stock_research" else "stock_research_tests"
            path.write_text(
                "".join(
                    f"{key}={json.dumps(value)}\n"
                    for key, value in database_environment(user, name).items()
                )
            )
            path.chmod(0o600)
    # The test role gets its own empty base DB; it cannot connect to development data.
    result = docker(
        "exec",
        CONTAINER,
        "psql",
        "-h",
        "/var/run/postgresql",
        "-U",
        "stock_bootstrap_admin",
        "-d",
        "postgres",
        "-tAc",
        "SELECT 1 FROM pg_database WHERE datname='stock_research_tests'",
    )
    if result.stdout.strip() != "1":
        docker(
            "exec",
            CONTAINER,
            "createdb",
            "-h",
            "/var/run/postgresql",
            "-U",
            "stock_bootstrap_admin",
            "-O",
            "stock_research_test",
            "stock_research_tests",
        )
    print("Private local PostgreSQL ready; role settings are in ignored .local files.")


if __name__ == "__main__":
    try:
        start()
    except subprocess.CalledProcessError as error:
        # Registry errors can contain URLs; keep command/output out of generic reports.
        raise SystemExit(
            "A local Docker operation failed; inspect daemon/registry readiness safely."
        ) from error
