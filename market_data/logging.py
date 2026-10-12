"""Sanitize the query-key authentication supported by Intrinio's documented API."""

import logging
import re
import traceback
from urllib.parse import quote, quote_plus

from django.conf import settings


class SecretRedactionFilter(logging.Filter):
    def filter(self, record):
        key = settings.INTRINIO_API_KEY

        def redact(text):
            if key:
                for value in {key, quote(key, safe=""), quote_plus(key)}:
                    text = text.replace(value, "[REDACTED]")
            return re.sub(r"(\bapi_key=)[^&\s\"']+", r"\1[REDACTED]", text, flags=re.I)

        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True
