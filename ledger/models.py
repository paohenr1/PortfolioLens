"""Immutable user journal, not a brokerage feed or market-data cache."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Round

from ledger.domain import KINDS, EventInput


class Entry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey("portfolios.Portfolio", on_delete=models.PROTECT)
    client_key = models.UUIDField()
    kind = models.CharField(
        max_length=10,
        choices=[(kind, kind.title()) for kind in KINDS],
    )
    event_date = models.DateField()
    sequence = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD", editable=False)
    security_id = models.CharField(max_length=100, blank=True)
    security_ticker = models.CharField(max_length=50, blank=True)
    exchange_mic = models.CharField(max_length=4, blank=True)
    reference_retrieved_at = models.DateTimeField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    fees = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    recorded_at = models.DateTimeField(auto_now_add=True)
    split_new = models.PositiveIntegerField(null=True, blank=True)
    split_old = models.PositiveIntegerField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0, editable=False)
    is_replacement = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ("event_date", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("portfolio", "client_key"), name="ledger_client_key_unique"
            ),
            models.UniqueConstraint(
                fields=("portfolio", "event_date", "sequence", "revision"),
                name="ledger_order_unique",
            ),
            models.CheckConstraint(condition=models.Q(currency="USD"), name="ledger_usd_only"),
            models.CheckConstraint(
                condition=models.Q(revision__lte=1000), name="ledger_revision_range"
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1, sequence__lte=999999),
                name="ledger_sequence_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(amount__lte=1000000000000, fees__gte=0, fees__lte=1000000000000)
                    & (
                        models.Q(kind="SPLIT", amount=0)
                        | (~models.Q(kind="SPLIT") & models.Q(amount__gt=0))
                    )
                ),
                name="ledger_money_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=("DEPOSIT", "WITHDRAWAL", "FEE"),
                        security_id="",
                        security_ticker="",
                        exchange_mic="",
                        reference_retrieved_at__isnull=True,
                        quantity__isnull=True,
                        unit_price__isnull=True,
                        fees=0,
                        split_new__isnull=True,
                        split_old__isnull=True,
                    )
                    | models.Q(
                        kind__in=("BUY", "SELL"),
                        security_id__regex=r"^[A-Za-z0-9_-]{1,100}$",
                        security_ticker__regex=r"\S",
                        exchange_mic__regex=r"^[A-Z0-9]{4}$",
                        reference_retrieved_at__isnull=False,
                        quantity__isnull=False,
                        unit_price__isnull=False,
                        quantity__gt=0,
                        quantity__lte=1000000000,
                        unit_price__gt=0,
                        unit_price__lte=1000000000,
                        split_new__isnull=True,
                        split_old__isnull=True,
                    )
                    | (
                        models.Q(
                            kind__in=("DIVIDEND", "SPLIT"),
                            security_id__regex=r"^[A-Za-z0-9_-]{1,100}$",
                            security_ticker__regex=r"\S",
                            exchange_mic__regex=r"^[A-Z0-9]{4}$",
                            reference_retrieved_at__isnull=False,
                            quantity__isnull=True,
                            unit_price__isnull=True,
                            fees=0,
                        )
                        & (
                            models.Q(
                                kind="DIVIDEND", split_new__isnull=True, split_old__isnull=True
                            )
                            | (
                                models.Q(
                                    kind="SPLIT",
                                    split_new__isnull=False,
                                    split_old__isnull=False,
                                    split_new__gte=1,
                                    split_new__lte=1000000,
                                    split_old__gte=1,
                                    split_old__lte=1000000,
                                )
                                & ~models.Q(split_new=models.F("split_old"))
                            )
                        )
                    )
                ),
                name="ledger_event_shape",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=("DEPOSIT", "WITHDRAWAL", "FEE", "DIVIDEND", "SPLIT"))
                    | models.Q(
                        amount=Round(models.F("quantity") * models.F("unit_price"), precision=2)
                    )
                ),
                name="ledger_trade_amount",
            ),
        ]

    def as_input(self):
        return EventInput(
            kind=self.kind,
            event_date=self.event_date,
            sequence=self.sequence,
            security_id=self.security_id,
            quantity=self.quantity,
            unit_price=self.unit_price,
            amount=None if self.kind in ("BUY", "SELL", "SPLIT") else self.amount,
            fees=self.fees,
            currency=self.currency,
            split_new=self.split_new,
            split_old=self.split_old,
        )

    @property
    def cash_delta(self):
        return self.as_input().cash_delta

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Ledger entries cannot be edited.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries cannot be deleted.")


class Correction(models.Model):
    """A permanent void/replacement decision, separate from investment cash flows."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey("portfolios.Portfolio", on_delete=models.PROTECT)
    target = models.OneToOneField(Entry, on_delete=models.PROTECT, related_name="voided_by")
    replacement = models.OneToOneField(
        Entry, null=True, blank=True, on_delete=models.PROTECT, related_name="replacement_for"
    )
    client_key = models.UUIDField()
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("recorded_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("portfolio", "client_key"), name="correction_client_key_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(reason__regex=r"\S"), name="correction_reason_nonblank"
            ),
            models.CheckConstraint(
                condition=~models.Q(target=models.F("replacement")), name="correction_not_self"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Corrections cannot be edited.")
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Corrections cannot be deleted.")
