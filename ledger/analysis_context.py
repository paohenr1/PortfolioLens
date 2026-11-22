"""Remember date preferences only; never store results or assume confirmations."""

from datetime import date, timedelta

from ledger.forms import ledger_today

SESSION_KEY = "portfolio_analysis_dates"
MAX_CONTEXTS = 50


def _key(request, portfolio_id):
    return f"{request.user.pk}:{portfolio_id}"


def _saved(request, portfolio_id):
    contexts = request.session.get(SESSION_KEY, {})
    if not isinstance(contexts, dict):
        return {}
    values = contexts.get(_key(request, portfolio_id), {})
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


def analysis_form(request, portfolio_id, form_type):
    form = form_type(request.POST if request.method == "POST" else None)
    form.date_notice = ""
    if request.method != "GET":
        return form
    saved = _saved(request, portfolio_id)
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
    dates = _saved(request, portfolio_id)
    for name in ("start_date", "end_date"):
        if name in form.cleaned_data:
            dates[name] = form.cleaned_data[name]
    if "as_of" in form.cleaned_data:
        dates["end_date"] = form.cleaned_data["as_of"]
    contexts = request.session.get(SESSION_KEY, {})
    contexts = dict(contexts) if isinstance(contexts, dict) else {}
    contexts.pop(_key(request, portfolio_id), None)
    contexts[_key(request, portfolio_id)] = {
        name: value.isoformat() for name, value in dates.items()
    }
    updated = dict(list(contexts.items())[-MAX_CONTEXTS:])
    if request.session.get(SESSION_KEY) != updated:
        request.session[SESSION_KEY] = updated
        # SessionMiddleware does not save 5xx responses. Persist preferences before
        # provider I/O so an unavailable feed does not discard the chosen dates.
        request.session.save()
        request.session.modified = False
