"""Turn parsed holdings plus market data into base-currency values.

The join point between `src.ingest` (what the user holds) and `src.market` (what it is
worth). Everything downstream reads `ValuedHolding`, so no risk module needs to know
about tickers, currencies, or providers.

A holding that cannot be priced keeps its identity and its cost basis but carries
`value=None`. It is shown to the user and excluded from every weight — a stale or
missing mark must never dilute a concentration figure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from src.ingest.schema import Holding
from src.market.fx import FxRates, convert_series
from src.market.metadata import resolve_asset_class
from src.market.prices import PriceFetchError, PriceHistory, UnresolvedTicker


@dataclass(frozen=True)
class ValuedHolding:
    """A holding with market value attached, in the reporting currency."""

    ticker: str
    quantity: float
    name: str | None = None
    cost_basis: float | None = None
    value: float | None = None
    price_native: float | None = None
    currency: str | None = None
    asset_class: str | None = None
    asset_class_inferred: bool = False
    theme: str | None = None
    sector: str | None = None
    isin: str | None = None
    insufficient_history: bool = False
    points: int = 0
    unavailable_reason: str | None = None
    closes_base: pd.Series | None = field(default=None, repr=False, compare=False)

    @property
    def resolved(self) -> bool:
        return bool(self.ticker)

    @property
    def priced(self) -> bool:
        return self.value is not None

    @property
    def usable_for_risk(self) -> bool:
        """Priced, with enough history for dispersion statistics."""
        return self.priced and not self.insufficient_history and self.closes_base is not None


@dataclass(frozen=True)
class ValuedPortfolio:
    holdings: list[ValuedHolding]
    base_currency: str
    fx: FxRates | None = None
    as_of: pd.Timestamp | None = None

    @property
    def priced(self) -> list[ValuedHolding]:
        return [h for h in self.holdings if h.priced]

    @property
    def unpriced(self) -> list[ValuedHolding]:
        return [h for h in self.holdings if not h.priced]

    @property
    def total_value(self) -> float:
        return float(sum(h.value or 0.0 for h in self.holdings))

    @property
    def total_cost_basis(self) -> float | None:
        """None if any holding lacks a basis — a partial sum would misstate P&L."""
        if any(h.cost_basis is None for h in self.holdings):
            return None
        return float(sum(h.cost_basis or 0.0 for h in self.holdings))

    @property
    def unrealised_pnl(self) -> float | None:
        basis = self.total_cost_basis
        return None if basis is None else self.total_value - basis


def value_portfolio(
    holdings: list[Holding],
    *,
    repo,
    base_currency: str,
    fx_series: Mapping[str, pd.Series] | None = None,
    fx_rates: FxRates | None = None,
) -> ValuedPortfolio:
    """Price every holding and convert into `base_currency`.

    Args:
        holdings: Parsed rows from `src.ingest.loader`.
        repo: Anything satisfying the `PriceRepository` protocol.
        base_currency: Reporting currency.
        fx_series: Currency -> EUR-pivoted rate series, for converting price history.
        fx_rates: Point-in-time table used for the latest value and for provenance.
    """
    valued: list[ValuedHolding] = []
    stamps: list[pd.Timestamp] = []

    for holding in holdings:
        if not holding.ticker:
            valued.append(_unavailable(holding, "no ticker supplied"))
            continue

        try:
            history: PriceHistory = repo.history(holding.ticker)
        except UnresolvedTicker:
            valued.append(_unavailable(holding, "ticker not found"))
            continue
        except PriceFetchError as exc:
            valued.append(_unavailable(holding, str(exc)))
            continue

        native = history.meta.currency
        try:
            closes_base = convert_series(
                history.closes, native=native, base=base_currency, fx=fx_series
            )
        except Exception:
            valued.append(_unavailable(holding, f"no {native} exchange rate"))
            continue

        clean = closes_base.dropna()
        if clean.empty:
            valued.append(_unavailable(holding, "no overlapping price and rate history"))
            continue

        price_base = float(clean.iloc[-1])
        asset_class, inferred = resolve_asset_class(
            declared=holding.asset_class, quote_type=history.meta.quote_type
        )
        stamps.append(clean.index[-1])
        valued.append(
            ValuedHolding(
                ticker=holding.ticker,
                quantity=holding.quantity,
                name=holding.name or history.meta.name,
                cost_basis=holding.cost_basis,
                value=price_base * holding.quantity,
                price_native=history.last_close,
                currency=native,
                asset_class=asset_class,
                asset_class_inferred=inferred,
                theme=holding.theme,
                sector=getattr(holding, "sector", None),
                isin=holding.isin,
                insufficient_history=history.insufficient_history,
                points=history.points,
                closes_base=clean,
            )
        )

    return ValuedPortfolio(
        holdings=valued,
        base_currency=base_currency,
        fx=fx_rates,
        as_of=max(stamps) if stamps else None,
    )


def _unavailable(holding: Holding, reason: str) -> ValuedHolding:
    return ValuedHolding(
        ticker=holding.ticker,
        quantity=holding.quantity,
        name=holding.name,
        cost_basis=holding.cost_basis,
        value=None,
        asset_class=holding.asset_class,
        theme=holding.theme,
        sector=getattr(holding, "sector", None),
        isin=holding.isin,
        unavailable_reason=reason,
    )
