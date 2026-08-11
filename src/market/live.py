"""Live market data wiring.

The only module that talks to a provider. Kept separate from `prices.py` and `fx.py`
so those stay pure and testable, and so the test suite never imports yfinance.

FX pairs are fetched *after* the instruments, because a holding's pricing currency is
only known once its history has been fetched. The repository caches, so the second pass
costs nothing.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from src.market.fx import PIVOT, SUBUNITS
from src.market.prices import (
    CachedPriceRepository,
    UnresolvedTicker,
    yfinance_fetcher,
)

DEFAULT_BENCHMARK = "^GSPC"


def build_repository(ttl_seconds: float = 900) -> CachedPriceRepository:
    return CachedPriceRepository(fetcher=yfinance_fetcher, ttl_seconds=ttl_seconds)


def currencies_for(repo, tickers: Iterable[str]) -> dict[str, str]:
    """Map ticker -> pricing currency, skipping anything that will not resolve."""
    found: dict[str, str] = {}
    for ticker in tickers:
        if not ticker:
            continue
        try:
            found[ticker] = repo.history(ticker).meta.currency
        except Exception:
            continue
    return found


def fx_series_for(repo, currencies: Iterable[str]) -> dict[str, pd.Series]:
    """Fetch the EUR-pivoted rate series needed to convert the given currencies.

    Sub-unit quotes (`GBp`) resolve to their major currency, so pence and pounds share
    one fetch.
    """
    needed: set[str] = set()
    for code in currencies:
        if not code or code == PIVOT:
            continue
        needed.add(SUBUNITS[code][0] if code in SUBUNITS else code)

    series: dict[str, pd.Series] = {}
    for code in sorted(needed):
        try:
            series[code] = repo.history(f"{PIVOT}{code}=X").closes
        except UnresolvedTicker:
            continue
    return series


def benchmark_closes(
    repo, *, symbol: str, base_currency: str, fx_series: dict[str, pd.Series]
) -> pd.Series | None:
    """Benchmark history converted into the reporting currency, or None if unavailable."""
    from src.market.fx import convert_series

    try:
        history = repo.history(symbol)
    except Exception:
        return None
    try:
        return convert_series(
            history.closes,
            native=history.meta.currency,
            base=base_currency,
            fx=fx_series,
        )
    except Exception:
        return None
