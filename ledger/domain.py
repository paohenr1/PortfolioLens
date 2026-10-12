"""Pure Decimal cash/share replay; no database, provider, or valuation assumptions."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

ZERO = Decimal("0")
CENT = Decimal("0.01")
MONEY_LIMIT = Decimal("1000000000000")
UNIT_LIMIT = Decimal("1000000000")
KINDS = ("DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "FEE", "DIVIDEND", "SPLIT")
TRADES = ("BUY", "SELL")
REFERENCED = (*TRADES, "DIVIDEND", "SPLIT")


def split_quantity(quantity, new, old):
    """Never round a split into or out of ownership; cash-in-lieu is separate work."""
    units = Fraction(quantity) * new * 1000000 / old
    if units.denominator != 1 or not 0 < units.numerator <= 10**18:
        raise LedgerRuleError(
            "This split cannot preserve each open lot exactly within six share decimals "
            "and the 1-trillion-share limit. Fraction rounding and cash-in-lieu are unsupported."
        )
    with localcontext() as context:
        context.prec = 64
        return Decimal(units.numerator).scaleb(-6)


class LedgerRuleError(ValueError):
    pass


def number(value, label, places, limit, *, positive=True):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise LedgerRuleError(f"{label} must be a finite decimal.")
    if value < ZERO or (positive and value == ZERO) or value > limit:
        raise LedgerRuleError(f"{label} is outside the supported range.")
    if value.as_tuple().exponent < -places:
        raise LedgerRuleError(f"{label} supports at most {places} decimal places.")
    if value.as_tuple().exponent > 12 or len(value.as_tuple().digits) > 24:
        raise LedgerRuleError(f"{label} exceeds the supported precision.")


@dataclass(frozen=True)
class EventInput:
    kind: str
    event_date: date
    sequence: int
    security_id: str = ""
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    fees: Decimal = ZERO
    currency: str = "USD"
    split_new: int | None = None
    split_old: int | None = None

    @property
    def gross_amount(self):
        if self.kind == "SPLIT":
            return ZERO
        if self.kind in TRADES:
            # Round a positive trade notional once, at the USD cash boundary.
            with localcontext() as context:
                context.prec = 64
                return (self.quantity * self.unit_price).quantize(CENT, rounding=ROUND_HALF_UP)
        return self.amount

    @property
    def cash_delta(self):
        with localcontext() as context:
            context.prec = 64
            if self.kind == "SPLIT":
                return ZERO
            if self.kind == "BUY":
                return -(self.gross_amount + self.fees)
            if self.kind == "SELL":
                return self.gross_amount - self.fees
            return self.gross_amount if self.kind in ("DEPOSIT", "DIVIDEND") else -self.gross_amount

    def validate(self, today):
        if self.currency != "USD":
            raise LedgerRuleError("Only USD transactions are supported.")
        if self.kind not in KINDS:
            raise LedgerRuleError("Choose a supported transaction type.")
        if type(self.event_date) is not date or not date(1900, 1, 1) <= self.event_date <= today:
            raise LedgerRuleError("Use a transaction date from 1900 through today (Toronto time).")
        if type(self.sequence) is not int or not 1 <= self.sequence <= 999999:
            raise LedgerRuleError("Same-day order must be an integer from 1 to 999999.")
        number(self.fees, "Fees", 2, MONEY_LIMIT, positive=False)
        if self.kind == "SPLIT":
            if (
                not self.security_id
                or any(value is not None for value in (self.amount, self.quantity, self.unit_price))
                or self.fees
            ):
                raise LedgerRuleError(
                    "Splits require only a security ID and a new-to-old share ratio."
                )
            if (
                any(
                    type(value) is not int or not 1 <= value <= 1000000
                    for value in (self.split_new, self.split_old)
                )
                or self.split_new == self.split_old
            ):
                raise LedgerRuleError("Use distinct positive integer split terms up to 1,000,000.")
            return
        if self.split_new is not None or self.split_old is not None:
            raise LedgerRuleError("Split ratio fields are for Split entries only.")
        if self.kind == "DIVIDEND":
            if (
                not self.security_id
                or self.quantity is not None
                or self.unit_price is not None
                or self.fees
            ):
                raise LedgerRuleError("Dividends require a security ID and net cash received only.")
            number(self.amount, "Net dividend cash", 2, MONEY_LIMIT)
            return
        if self.kind in TRADES:
            # Import no provider logic: stable ID syntax is checked by the web/service boundary.
            if not self.security_id or self.amount is not None:
                raise LedgerRuleError("Trades require a security ID and no cash-movement amount.")
            number(self.quantity, "Quantity", 6, UNIT_LIMIT)
            number(self.unit_price, "Execution price", 6, UNIT_LIMIT)
            number(self.gross_amount, "Rounded trade value", 2, MONEY_LIMIT)
        else:
            if (
                self.security_id
                or self.quantity is not None
                or self.unit_price is not None
                or self.fees
            ):
                raise LedgerRuleError(
                    "Cash movements use only the amount; record separate fees as Fee entries."
                )
            number(self.amount, "Amount", 2, MONEY_LIMIT)


@dataclass(frozen=True)
class Replay:
    cash: Decimal
    quantities: dict[str, Decimal]


def replay(events):
    """Reject negative balances at every historical prefix, not only at the end."""
    cash, quantities, orders = ZERO, {}, set()
    with localcontext() as context:
        context.prec = 64
        for event in sorted(events, key=lambda item: (item.event_date, item.sequence)):
            order = (event.event_date, event.sequence)
            if order in orders:
                raise LedgerRuleError(
                    "That same-day order is already used. Choose a distinct order number."
                )
            orders.add(order)
            if event.kind in TRADES:
                quantity = quantities.get(event.security_id, ZERO)
                quantity += event.quantity if event.kind == "BUY" else -event.quantity
                if quantity < ZERO:
                    raise LedgerRuleError(
                        "This entry would create a short position. Check quantity, date, and order."
                    )
                quantities[event.security_id] = quantity
            elif event.kind == "SPLIT":
                if quantities.get(event.security_id, ZERO) <= ZERO:
                    raise LedgerRuleError(
                        "A split requires an open position at its date and order."
                    )
                quantities[event.security_id] = split_quantity(
                    quantities[event.security_id], event.split_new, event.split_old
                )
            cash += event.cash_delta
            if cash < ZERO:
                raise LedgerRuleError(
                    "This entry would make recorded cash negative. Check amount, date, and order."
                )
        cash = cash.quantize(CENT)
    return Replay(cash, quantities)
