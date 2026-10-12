"""Explicit, bounded quote loading for a private immutable journal snapshot."""

import logging

from ledger.services import SUPPORTED_MICS
from ledger.valuation import value_snapshot
from market_data.errors import ProviderError, ProviderRateLimited
from research import services as market_data

MAX_VALUATION_INSTRUMENTS = 5
logger = logging.getLogger("research")


class ValuationLimitError(ValueError):
    pass


def load_valuation(analysis, labels, as_of, client_address):
    if len(analysis.positions) > MAX_VALUATION_INSTRUMENTS:
        raise ValuationLimitError(
            "Valuation supports at most five open instruments on the selected date."
        )
    histories, issues, error = {}, {}, None
    for position in analysis.positions:
        # A rate limit stops this action immediately instead of spending more quota.
        if isinstance(error, ProviderRateLimited):
            issues[position.security_id] = error.message
            continue
        if labels[position.security_id].exchange_mic not in SUPPORTED_MICS:
            # Fail closed for an unsupported stored venue before spending quota.
            continue
        try:
            histories[position.security_id] = market_data.daily_prices(
                position.security_id, as_of, client_address
            )
        except ProviderError as failure:
            issues[position.security_id] = failure.message
            if error is None or isinstance(failure, ProviderRateLimited):
                error = failure
        except Exception:
            # Exception details may contain authenticated URLs or provider echoes.
            # Record only the fixed operation name, without the exception/trace.
            logger.error("Unexpected portfolio valuation price failure")
            issues[position.security_id] = ProviderError.message
            error = error or ProviderError()
    return (
        value_snapshot(
            analysis,
            as_of,
            histories,
            {identifier: entry.exchange_mic for identifier, entry in labels.items()},
            issues=issues,
        ),
        error,
    )
