from datetime import timedelta
from decimal import Decimal

import exchange_calendars
from django import forms

from ledger.daily_returns import session_dates
from ledger.forms import ledger_today
from ledger.performance import PerformanceRuleError
from ledger.performance_forms import PerformanceForm
from market_data.fields import valid_provider_id


class DailyReturnForm(PerformanceForm):
    benchmark_id = forms.CharField(
        required=False,
        max_length=100,
        label="Optional benchmark security ID",
        help_text="Find the stable security ID on an instrument's research page. "
        "Leave blank for portfolio returns only. The benchmark uses provider-adjusted closes.",
    )
    annual_risk_free_percent = forms.DecimalField(
        required=False,
        max_digits=7,
        decimal_places=4,
        min_value=Decimal(-100),
        max_value=Decimal(100),
        label="Optional risk-free rate · annual simple %",
        help_text="Enter your constant assumption, including 0 if intended. "
        "Divided by 252 per session; this is not an effective compounded yield. "
        "Leave blank to skip Sharpe.",
    )
    sharpe_assumption_checked = forms.BooleanField(
        required=False,
        label="I confirm this constant annual simple-rate assumption and the "
        "252-session Sharpe annualization convention.",
    )

    def clean_benchmark_id(self):
        identifier = self.cleaned_data["benchmark_id"]
        if identifier and not valid_provider_id(identifier):
            raise forms.ValidationError("Choose a valid stable security ID.")
        return identifier

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            end = ledger_today() - timedelta(days=1)
            start = end - timedelta(days=30)
            calendar = exchange_calendars.get_calendar(
                "XNYS", start=start - timedelta(days=7), end=end + timedelta(days=7)
            )
            days = calendar.sessions_in_range(start, end)
            self.initial.update(start_date=days[0].date(), end_date=days[-1].date())

    def clean(self):
        values = super().clean()
        rate, confirmed = (
            values.get("annual_risk_free_percent"),
            values.get("sharpe_assumption_checked"),
        )
        if rate is not None and not confirmed:
            self.add_error(
                "sharpe_assumption_checked", "Confirm the risk-free assumption to load Sharpe."
            )
        elif confirmed and rate is None and "annual_risk_free_percent" not in self.errors:
            self.add_error(
                "annual_risk_free_percent",
                "Enter an explicit risk-free rate, including zero if intended.",
            )
        start, end = values.get("start_date"), values.get("end_date")
        if start and end:
            try:
                session_dates(start, end)
            except PerformanceRuleError as error:
                raise forms.ValidationError(str(error)) from None
        return values
