"""Isolated test worker; only a generated Django test database is permitted."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402

from operations.rate_limits import reserve  # noqa: E402

if not settings.DATABASES["default"]["NAME"].startswith("test_"):
    raise SystemExit("Rate-limit workers require an isolated test database.")

with patch("operations.rate_limits._database_now", return_value=65):
    admitted = sum(reserve("market", "process-fixture") is None for _ in range(10))
print(json.dumps({"admitted": admitted}))
