"""Remember date preferences only; never store results or assume confirmations."""

from datetime import date, timedelta

from config.session_backend import ANALYSIS_DATES_KEY
from ledger.forms import ledger_today

MAX_CONTEXTS = 50


def _key(request, portfolio_id):
    return f"{request.user.pk}:{portfolio_id}"


def _saved(contexts, key):
    values = contexts.get(key, {})
    if not isinstance(values, dict):
        return {}
    result = {}
    for name in ("start_date", "end_date"):
        value = values.get(name)
        if not isinstance(value, str) or len(value) != 10:
            continue
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            continue
        if parsed.isoformat() == value and date(1900, 1, 1) <= parsed < ledger_today():
            result[name] = parsed
    return result


def saved_dates(request, portfolio_id):
    contexts = request.session.get(ANALYSIS_DATES_KEY, {})
    return _saved(contexts, _key(request, portfolio_id)) if isinstance(contexts, dict) else {}


def analysis_form(request, portfolio_id, form_type):
    form = form_type(request.POST if request.method == "POST" else None)
    form.date_notice = ""
    if request.method != "GET":
        return form
    saved = saved_dates(request, portfolio_id)
    if not saved:
        return form
    if "as_of" in form.fields and "end_date" in saved:
        form.initial["as_of"] = saved["end_date"]
        dates = {"as_of": saved["end_date"]}
    elif "end_date" in form.fields:
        if "end_date" in saved and "start_date" not in saved:
            saved["start_date"] = max(date(1900, 1, 1), saved["end_date"] - timedelta(days=30))
        form.initial.update(saved)
        dates = {name: form.initial[name] for name in ("start_date", "end_date")}
    else:
        return form
    # Validate dates only for an early explanation; actual confirmations remain unchecked.
    probe = form_type(dates)
    probe.is_valid()
    issues = list(probe.non_field_errors())
    for name in dates:
        issues.extend(probe.errors.get(name, ()))
    if issues:
        form.date_notice = "Your selected dates need adjusting here: " + " ".join(issues)
    return form


def remember_dates(request, portfolio_id, form):
    """Call after full form validation and ownership lookup, including on provider failure."""
    key = _key(request, portfolio_id)

    def update(contexts):
        dates = _saved(contexts, key)
        for name in ("start_date", "end_date"):
            if name in form.cleaned_data:
                dates[name] = form.cleaned_data[name]
        if "as_of" in form.cleaned_data:
            dates["end_date"] = form.cleaned_data["as_of"]
        remaining = [(name, value) for name, value in contexts.items() if name != key]
        remaining.append((key, {name: value.isoformat() for name, value in dates.items()}))
        return dict(remaining[-MAX_CONTEXTS:])

    # Persist the dates before provider I/O. The database session backend protects
    # this update from late responses and keeps it when middleware skips a 5xx.
    request.session.update_analysis_dates(update)
