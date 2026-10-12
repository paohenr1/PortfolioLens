"""Keep owner identity server-controlled and enforce creation atomically."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction

from portfolios.models import Portfolio

MAX_PORTFOLIOS_PER_USER = 50


class PortfolioStorageUnavailable(Exception):
    pass


def require_portfolio_storage():
    if connection.vendor != "postgresql":
        raise PortfolioStorageUnavailable


def owned_portfolios(user):
    require_portfolio_storage()
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    # UUIDs make guessing harder; the owner filter is the authorization boundary.
    return Portfolio.objects.filter(owner=user)


def create_portfolio(*, owner, name):
    require_portfolio_storage()
    if not owner.is_authenticated or not owner.is_active:
        raise PermissionDenied
    portfolio = Portfolio(owner=owner, name=name, reporting_currency="USD")
    portfolio.full_clean(validate_constraints=False)
    try:
        # Database uniqueness handles two requests racing for the same owner/name.
        with transaction.atomic():
            # Lock the owner so concurrent creations cannot exceed the allowance.
            current_owner = (
                owner.__class__.objects.select_for_update()
                .filter(pk=owner.pk, is_active=True)
                .first()
            )
            if current_owner is None:
                raise PermissionDenied
            if Portfolio.objects.filter(owner=owner).count() >= MAX_PORTFOLIOS_PER_USER:
                raise ValidationError({"__all__": "An account can have up to 50 portfolios."})
            portfolio.save(force_insert=True)
    except IntegrityError as error:
        if (
            getattr(error.__cause__, "diag", None)
            and error.__cause__.diag.constraint_name == "portfolio_owner_name_unique"
        ):
            raise ValidationError(
                {"name": "You already have a portfolio with this name."}
            ) from None
        raise
    return portfolio
