"""Public errors contain fixed messages, never provider bodies or request URLs."""


class ProviderError(Exception):
    code = "unavailable"
    status = 503
    message = "Market data is temporarily unavailable. Please try again later."
    retry_after: int | None = None

    def __init__(self):
        super().__init__(self.message)


class CredentialsMissing(ProviderError):
    code = "not_configured"
    message = "Market data unavailable: Intrinio is not configured."


class AuthenticationFailed(ProviderError):
    code = "authentication_failed"
    message = "Intrinio could not authenticate the configured credentials."


class EntitlementDenied(ProviderError):
    code = "entitlement_denied"
    message = "Intrinio did not grant access to this dataset. Check the subscription permissions."


class InstrumentNotFound(ProviderError):
    code = "not_found"
    status = 404
    message = "This instrument was not found in the available data feed."


class InvalidResponse(ProviderError):
    code = "invalid_response"
    message = "Intrinio returned data that could not be validated. Please try again later."


class CompanyUnavailable(ProviderError):
    code = "company_unavailable"
    message = "Company fundamentals are unavailable: this instrument has no company identity."


class StatementUnavailable(ProviderError):
    code = "statement_unavailable"
    status = 404
    message = "No financial statement is available for the requested fiscal year and period."


class MarketCapitalizationUnavailable(ProviderError):
    code = "market_capitalization_unavailable"
    status = 404
    message = "No company market capitalization is available from the requested data feed."


class ProviderRateLimited(ProviderError):
    code = "rate_limited"
    status = 429
    message = "The market-data request limit has been reached. Please wait before trying again."

    def __init__(self, retry_after: int = 60):
        self.retry_after = max(1, min(retry_after, 3600))
        super().__init__()
