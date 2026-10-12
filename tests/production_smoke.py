"""Real Gunicorn/WhiteNoise smoke, no hosted DB, provider calls or stored users."""

import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def environment():
    # Preserve proxy/CA/runtime bindings; isolate only application/server settings.
    environ = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("DJANGO_", "STOCK_", "GUNICORN_"))
    }
    environ.update(
        DJANGO_ENV="production",
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
        DJANGO_ALLOWED_HOSTS="127.0.0.1",
        DJANGO_DATABASE_ENGINE="postgresql",
        DJANGO_DATABASE_NAME="unused_fixture_database",
        DJANGO_DATABASE_USER="unused_fixture_user",
        DJANGO_DATABASE_HOST="127.0.0.1",
        DJANGO_DATABASE_PORT="1",
        DJANGO_DATABASE_PASSWORD="synthetic-only-unused-password",
        DJANGO_DATABASE_SSLMODE="verify-full",
        INTRINIO_API_KEY="",
        STOCK_WORKERS="2",
        STOCK_BIND_HOST="127.0.0.1",
    )
    return environ


@contextmanager
def server(environ, diagnostics):
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    child = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/start_production.py")],
        cwd=ROOT,
        env={**environ, "PORT": str(port)},
        stdout=diagnostics,
        stderr=diagnostics,
        start_new_session=True,
    )
    try:
        # The process group belongs only to this child and its Gunicorn workers.
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            for _ in range(60):
                if child.poll() is not None:
                    raise RuntimeError("The owned production smoke server failed to start.")
                try:
                    if client.get("/health/live/").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Production smoke liveness did not become ready.")
            yield client, port
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
                raise RuntimeError("Owned Gunicorn smoke workers did not stop cleanly.") from None
        if child.returncode != 0:
            raise RuntimeError("The owned production smoke server exited unexpectedly.")


def main():
    environ = environment()
    subprocess.run(
        [sys.executable, "manage.py", "collectstatic", "--noinput"],
        cwd=ROOT,
        env=environ,
        check=True,
        timeout=30,
    )
    with tempfile.TemporaryFile(mode="w+") as diagnostics:
        with server(environ, diagnostics) as (client, _):
            assert client.get("/health/live/").json() == {"status": "alive"}
            # Gunicorn itself must not turn a supplied scheme header into HTTPS.
            assert client.get("/", headers={"X-Forwarded-Proto": "https"}).status_code == 301
            assert client.get("/").status_code == 301
            print("Gunicorn default: untrusted scheme header ignored; liveness PASS.")
        with server({**environ, "DJANGO_TRUST_PROXY_HTTPS": "true"}, diagnostics) as (client, port):
            proxy = {"X-Forwarded-Proto": "https"}
            for route in ("/", "/search/?q=AAPL", "/stocks/sec_fixture_primary/prices/"):
                response = client.get(route, headers=proxy)
                assert response.status_code == 302
                assert response.headers["location"].startswith("/sign-in/?next=")
                assert "no-store" in response.headers["cache-control"]
            form = client.get("/sign-in/", headers=proxy)
            assert form.status_code == 200 and 'href="/register/"' not in form.text
            assert "max-age=3600" in form.headers["strict-transport-security"]
            assert "Secure" in form.headers["set-cookie"]
            assert client.get("/register/", headers=proxy).status_code == 404
            asset = re.search(r'href="(/static/research/site\.[0-9a-f]+\.css)"', form.text)
            assert asset, "Production stylesheet did not use its collected fingerprint."
            stylesheet = client.get(asset.group(1), headers={**proxy, "Accept-Encoding": "gzip"})
            assert stylesheet.status_code == 200 and ".volume-bar" in stylesheet.text
            assert stylesheet.headers["content-encoding"] == "gzip"
            assert "immutable" in stylesheet.headers["cache-control"]
            assert "frame-ancestors 'none'" in stylesheet.headers["content-security-policy"]
            assert (
                client.get("/health/live/", headers={"Host": "untrusted.example"}).status_code
                == 400
            )
            # The deliberately unused loopback database is unavailable. A valid
            # CSRF account POST must fail closed before authentication or mutation.
            token = client.cookies.get("csrftoken")
            failure = client.post(
                "/sign-in/",
                headers={
                    **proxy,
                    "Cookie": "csrftoken=" + token,
                    "X-CSRFToken": token,
                    "Origin": f"https://127.0.0.1:{port}",
                },
                data={"username": "unused-fixture", "password": "synthetic-unused-pass-94"},
            )
            assert failure.status_code == 503
            assert "no-store" in failure.headers["cache-control"]
            assert "synthetic-unused-pass-94" not in failure.text
            print(
                "Gunicorn opt-in proxy: private routes, closed registration and safe failure PASS."
            )
            print(
                "WhiteNoise: fingerprinted gzip asset, immutable cache and security headers PASS."
            )
    print("Production runtime smoke PASS; two workers per server, owned processes stopped.")


if __name__ == "__main__":
    main()
