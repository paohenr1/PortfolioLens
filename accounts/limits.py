"""Bounded account attempts; production workers share PostgreSQL admission."""

import hashlib
import threading
import time

from django.conf import settings

CLIENT_ATTEMPTS_PER_MINUTE = 10
TOTAL_ATTEMPTS_PER_MINUTE = 60


class AttemptBudget:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._window = None
            self._total = 0
            self._clients = {}

    def reserve(self, address):
        now = int(time.monotonic())
        identity = hashlib.sha256(address.encode()).hexdigest()
        with self._lock:
            if now // 60 != self._window:
                self._window = now // 60
                self._total = 0
                self._clients.clear()
            count = self._clients.get(identity, 0)
            if count >= CLIENT_ATTEMPTS_PER_MINUTE or self._total >= TOTAL_ATTEMPTS_PER_MINUTE:
                return 60 - now % 60
            # Only admitted attempts create entries: no more than 60 hashes.
            # Do not lock user accounts: strangers could otherwise lock victims out.
            self._clients[identity] = count + 1
            self._total += 1
        return None


attempt_budget = AttemptBudget()


def reserve_attempt(address):
    if settings.RATE_LIMIT_BACKEND == "postgresql":
        from operations.rate_limits import reserve

        return reserve("auth", address)
    return attempt_budget.reserve(address)
