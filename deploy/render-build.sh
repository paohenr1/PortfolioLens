#!/usr/bin/env bash
# Native Python build: tools and application dependencies stay inside the checkout.
set -euo pipefail
cd "$(dirname "$0")/.."

python - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    raise SystemExit("This release requires Python 3.12.")
PY

# Bootstrap the same pinned tool as CI, without depending on Render's global uv.
# Inherited HTTPS proxy and CA settings remain in force; verification stays enabled.
python -m venv .render-tools
.render-tools/bin/python -m pip install --disable-pip-version-check uv==0.12.19
.render-tools/bin/python -m uv sync --frozen --no-dev

# These commands validate configuration and build public assets, without querying
# the application database or Intrinio. Migration/account creation are separate.
.render-tools/bin/python -m uv run --frozen --no-dev python manage.py check --deploy
.render-tools/bin/python -m uv run --frozen --no-dev python manage.py collectstatic --noinput
.render-tools/bin/python -m uv run --frozen --no-dev python - <<'PY'
from deploy.runtime import check_static_release, gunicorn_options
import os
gunicorn_options(os.environ)
check_static_release()
print("Production configuration and collected assets validated; database untouched.")
PY
