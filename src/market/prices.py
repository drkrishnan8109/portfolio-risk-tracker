"""Price history: a small repository interface, a cache, and two implementations.

The interface exists so tests never touch the network. `FrozenPriceRepository` reads the
captured fixtures; `CachedPriceRepository` wraps a live fetcher. Both satisfy the same
protocol, so every downstream module is provider-agnostic.

An unknown ticker raises rather than returning an empty series: an empty series flows
downstream as *zero value* instead of *unknown value*, which silently understates a
portfolio.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

#: Below this many observations, dispersion statistics are not meaningful.
MIN_HISTORY_DAYS = 60

DEFAULT_PERIOD = "2y"
DEFAULT_TTL_SECONDS = 15 * 60


class UnresolvedTicker(LookupError):
    """No price history exists for this symbol."""

    def __init__(self, ticker: str) -> None:
        super().__init__(f"No price history for {ticker!r}")
        self.ticker = ticker


class PriceFetchError(RuntimeError):
    """The provider failed. Distinct from `UnresolvedTicker`: this one is retryable."""

    def __init__(self, ticker: str, cause: BaseException) -> None:
        super().__init__(f"Could not fetch prices for {ticker!r}: {cause}")
        self.ticker = ticker


@dataclass(frozen=True)
class InstrumentMeta:
    ticker: str
    currency: str
    name: str | None = None
    quote_type: str | None = None
    exchange: str | None = None


@dataclass(frozen=True)
class PriceHistory:
    ticker: str
    closes: pd.Series
    meta: InstrumentMeta
    volumes: pd.Series | None = None

    @property
    def points(self) -> int:
        return int(self.closes.notna().sum())

    @property
    def insufficient_history(self) -> bool:
        """True when there are too few observations for volatility, beta or drawdown."""
        return self.points < MIN_HISTORY_DAYS

    @property
    def last_close(self) -> float:
        return float(self.closes.dropna().iloc[-1])

    @property
    def as_of(self) -> pd.Timestamp:
        return self.closes.dropna().index[-1]


class PriceRepository(Protocol):
    def history(self, ticker: str, *, period: str = DEFAULT_PERIOD) -> PriceHistory: ...


@dataclass
class FrozenPriceRepository:
    """Serves captured fixtures. Used by the whole test suite."""

    closes: Mapping[str, pd.Series]
    volumes: Mapping[str, pd.Series] = field(default_factory=dict)
    meta: Mapping[str, Mapping] = field(default_factory=dict)

    def history(self, ticker: str, *, period: str = DEFAULT_PERIOD) -> PriceHistory:
        if ticker not in self.closes:
            raise UnresolvedTicker(ticker)
        series = self.closes[ticker].dropna()
        if series.empty:
            raise UnresolvedTicker(ticker)
        info = dict(self.meta.get(ticker, {}))
        return PriceHistory(
            ticker=ticker,
            closes=series.sort_index(),
            volumes=self.volumes.get(ticker),
            meta=InstrumentMeta(
                ticker=ticker,
                currency=info.get("currency") or "USD",
                name=info.get("name"),
                quote_type=info.get("quote_type"),
                exchange=info.get("exchange"),
            ),
        )

    def __contains__(self, ticker: str) -> bool:
        return ticker in self.closes


#: A fetcher returns (closes, volumes, meta) or raises.
Fetcher = Callable[[str, str], tuple[pd.Series, pd.Series | None, InstrumentMeta | None]]


@dataclass
class CachedPriceRepository:
    """Wraps a fetcher with an in-memory, TTL'd cache keyed by (ticker, period).

    Failures are never cached: a transient network error must not poison the entry for
    the rest of the session.
    """

    fetcher: Fetcher
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    clock: Callable[[], float] = time.monotonic
    _cache: dict[tuple[str, str], tuple[float, PriceHistory]] = field(
        default_factory=dict, repr=False
    )

    def history(self, ticker: str, *, period: str = DEFAULT_PERIOD) -> PriceHistory:
        key = (ticker, period)
        now = self.clock()
        cached = self._cache.get(key)
        if cached is not None and now - cached[0] < self.ttl_seconds:
            return cached[1]

        try:
            closes, volumes, meta = self.fetcher(ticker, period)
        except (UnresolvedTicker, PriceFetchError):
            raise
        except Exception as exc:
            raise PriceFetchError(ticker, exc) from exc

        if closes is None or len(closes.dropna()) == 0:
            raise UnresolvedTicker(ticker)

        history = PriceHistory(
            ticker=ticker,
            closes=closes.dropna().sort_index(),
            volumes=volumes,
            meta=meta or InstrumentMeta(ticker=ticker, currency="USD"),
        )
        self._cache[key] = (now, history)
        return history

    def clear(self) -> None:
        self._cache.clear()


def yfinance_fetcher(ticker: str, period: str):  # pragma: no cover - network path
    """Live fetcher. Imported lazily so the test suite never needs yfinance installed."""
    import yfinance as yf

    handle = yf.Ticker(ticker)
    frame = handle.history(period=period, auto_adjust=False)
    if frame is None or frame.empty:
        raise UnresolvedTicker(ticker)

    closes = frame["Close"]
    closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
    volumes = frame.get("Volume")
    if volumes is not None:
        volumes.index = closes.index

    info = getattr(handle, "fast_info", None) or {}
    meta = InstrumentMeta(
        ticker=ticker,
        currency=(info.get("currency") if hasattr(info, "get") else None) or "USD",
        name=None,
        quote_type=(info.get("quote_type") if hasattr(info, "get") else None),
    )
    return closes, volumes, meta
