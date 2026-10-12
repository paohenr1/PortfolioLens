"""Validate configuration/artifacts, then replace this process with Gunicorn."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

from deploy.runtime import check_static_release, gunicorn_options  # noqa: E402


def main():
    try:
        gunicorn_options(os.environ)
        check_static_release()
    except ImproperlyConfigured as error:
        raise SystemExit(str(error)) from None
    os.chdir(ROOT)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "gunicorn",
            "--config",
            str(ROOT / "deploy/gunicorn.conf.py"),
            "config.wsgi:application",
        ],
    )


if __name__ == "__main__":
    main()
