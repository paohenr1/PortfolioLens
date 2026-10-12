"""Pure FIFO projection of immutable journal events; no quotes or database writes."""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction

from ledger.domain import CENT, ZERO, EventInput, replay, split_quantity


@dataclass(frozen=True)
class LotPortion:
    acquisition_date: date
    acquisition_order: int
    quantity: Decimal
    cost_basis: Decimal


@dataclass(frozen=True)
class Position:
    security_id: str
    quantity: Decimal
    cost_basis: Decimal
    lots: tuple[LotPortion, ...]


@dataclass(frozen=True)
class RealizedSale:
    security_id: str
    event_date: date
    sequence: int
    quantity: Decimal
    gross_proceeds: Decimal
    fees: Decimal
    net_proceeds: Decimal
    cost_basis: Decimal
    gain: Decimal
    lots: tuple[LotPortion, ...]


@dataclass(frozen=True)
class Analysis:
    cash: Decimal
    open_cost_basis: Decimal
    realized_gain: Decimal
    standalone_fees: Decimal
    net_dividends: Decimal
    positions: tuple[Position, ...]
    sales: tuple[RealizedSale, ...]


@dataclass
class _Lot:
    event: EventInput
    original_cost: Decimal
    remaining_quantity: Decimal
    original_quantity: Fraction
    allocated_cost: Decimal = ZERO

    def consume(self, quantity):
        self.remaining_quantity -= quantity
        # Allocate against ORIGINAL cost and cumulative shares sold. Rounding
        # each sale's fraction separately would make pennies depend on batching.
        # Exact rational cents avoid division precision changing half-cent ties.
        sold_fraction = 1 - Fraction(self.remaining_quantity) / self.original_quantity
        cents = Fraction(self.original_cost) * 100 * sold_fraction
        whole, remainder = divmod(cents.numerator, cents.denominator)
        cumulative = (Decimal(whole + (2 * remainder >= cents.denominator)) / 100).quantize(CENT)
        cost = cumulative - self.allocated_cost
        self.allocated_cost = cumulative
        return LotPortion(self.event.event_date, self.event.sequence, quantity, cost)

    def open_portion(self):
        return LotPortion(
            self.event.event_date,
            self.event.sequence,
            self.remaining_quantity,
            self.original_cost - self.allocated_cost,
        )

    def apply_split(self, new, old):
        self.remaining_quantity = split_quantity(self.remaining_quantity, new, old)
        # Scale ORIGINAL-equivalent shares too, including shares sold earlier.
        # Keeping this exact fraction preserves previous cent allocations and
        # avoids allocating previously sold cost a second time after a split.
        self.original_quantity *= Fraction(new, old)


def analyze(events):
    """Rebuild FIFO lots and sale gains; a bad journal never becomes a valid result."""
    events = list(events)
    for event in events:
        # The calculator has no wall clock; the write/read service enforces today's
        # ceiling. Shape, USD, precision, and historic-prefix checks still apply here.
        event.validate(date.max)
    events.sort(key=lambda item: (item.event_date, item.sequence))
    balances = replay(events)
    lots, sales = defaultdict(deque), []
    standalone_fees = ZERO
    net_dividends = ZERO
    with localcontext() as context:
        context.prec = 64
        for event in events:
            if event.kind == "BUY":
                # Commissions are capitalized once; standalone fees stay separate.
                lots[event.security_id].append(
                    _Lot(
                        event,
                        event.gross_amount + event.fees,
                        event.quantity,
                        Fraction(event.quantity),
                    )
                )
            elif event.kind == "SELL":
                remaining, portions = event.quantity, []
                queue = lots[event.security_id]
                while remaining:
                    lot = queue[0]
                    taken = min(remaining, lot.remaining_quantity)
                    portions.append(lot.consume(taken))
                    remaining -= taken
                    if not lot.remaining_quantity:
                        queue.popleft()
                basis = sum((portion.cost_basis for portion in portions), ZERO).quantize(CENT)
                proceeds = event.gross_amount - event.fees
                sales.append(
                    RealizedSale(
                        event.security_id,
                        event.event_date,
                        event.sequence,
                        event.quantity,
                        event.gross_amount,
                        event.fees,
                        proceeds,
                        basis,
                        proceeds - basis,
                        tuple(portions),
                    )
                )
            elif event.kind == "FEE":
                standalone_fees += event.amount
            elif event.kind == "DIVIDEND":
                net_dividends += event.amount
            elif event.kind == "SPLIT":
                for lot in lots[event.security_id]:
                    lot.apply_split(event.split_new, event.split_old)
        positions = tuple(
            Position(
                security_id,
                sum((lot.remaining_quantity for lot in queue), ZERO),
                sum((lot.original_cost - lot.allocated_cost for lot in queue), ZERO).quantize(CENT),
                tuple(lot.open_portion() for lot in queue),
            )
            for security_id, queue in sorted(lots.items())
            if queue
        )
        return Analysis(
            balances.cash,
            sum((position.cost_basis for position in positions), ZERO).quantize(CENT),
            sum((sale.gain for sale in sales), ZERO).quantize(CENT),
            standalone_fees.quantize(CENT),
            net_dividends.quantize(CENT),
            positions,
            tuple(sales),
        )
