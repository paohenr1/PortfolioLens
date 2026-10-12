"""Atomic PostgreSQL admission shared by all workers using this database."""

import hashlib
import re

from django.db import DatabaseError, connection, transaction

from operations.models import RequestBudgetState

POLICIES = {"market": (10, 30), "auth": (10, 60)}
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class BudgetUnavailable(Exception):
    """The caller must fail closed, without exposing database details."""


def _database_now():
    # One database clock keeps workers/restarts in the same minute window.
    with connection.cursor() as cursor:
        cursor.execute("SELECT floor(extract(epoch FROM clock_timestamp()))::bigint")
        return cursor.fetchone()[0]


def _valid_state(state, client_limit, total_limit):
    counts = state.clients
    return (
        type(state.window) is int
        and state.window >= 0
        and type(state.total) is int
        and 0 <= state.total <= total_limit
        and isinstance(counts, dict)
        and len(counts) <= total_limit
        and all(
            isinstance(key, str)
            and _DIGEST.fullmatch(key)
            and type(value) is int
            and 1 <= value <= client_limit
            for key, value in counts.items()
        )
        and sum(counts.values()) == state.total
    )


def reserve(scope, address):
    """Return None on admission or Retry-After seconds on denial; never refund."""
    if scope not in POLICIES:
        raise ValueError("Unsupported operational request scope.")
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        # A caller's later rollback must not refund an already dispatched call.
        raise BudgetUnavailable()
    client_limit, total_limit = POLICIES[scope]
    identity = hashlib.sha256(address.encode()).hexdigest()
    try:
        with transaction.atomic(durable=True):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '2s'")
                cursor.execute("SET LOCAL statement_timeout = '3s'")
            RequestBudgetState.objects.get_or_create(scope=scope)
            state = RequestBudgetState.objects.select_for_update().get(scope=scope)
            if not _valid_state(state, client_limit, total_limit):
                raise BudgetUnavailable()
            now = _database_now()
            if type(now) is not int or now < 0:
                raise BudgetUnavailable()
            # Never reset a counter when the database wall clock moves backward.
            if now // 60 > state.window:
                state.window, state.total, state.clients = now // 60, 0, {}
            count = state.clients.get(identity, 0)
            if state.total >= total_limit or count >= client_limit:
                return max(1, min((state.window + 1) * 60 - now, 3600))
            state.clients[identity] = count + 1
            state.total += 1
            state.save(update_fields=("window", "total", "clients"))
        # All locks are released before authentication work or provider HTTP.
        return None
    except DatabaseError:
        raise BudgetUnavailable() from None
