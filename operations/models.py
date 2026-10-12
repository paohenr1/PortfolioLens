"""Two bounded operational counters; no market data or raw client addresses."""

from django.db import models


class RequestBudgetState(models.Model):
    scope = models.CharField(
        primary_key=True, max_length=16, choices=(("market", "Market"), ("auth", "Authentication"))
    )
    window = models.PositiveBigIntegerField(default=0)
    total = models.PositiveSmallIntegerField(default=0)
    clients = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(scope__in=("market", "auth")), name="budget_scope"
            ),
            models.CheckConstraint(condition=models.Q(total__lte=60), name="budget_total_bound"),
        ]
