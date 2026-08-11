"""Tests P1-P6 — price history, caching, and asset-class metadata."""

from __future__ import annotations

import pandas as pd
import pytest

from src.market.metadata import infer_asset_class, resolve_asset_class
from src.market.prices import (
    MIN_HISTORY_DAYS,
    CachedPriceRepository,
    InstrumentMeta,
    PriceFetchError,
    UnresolvedTicker,
)


def test_p1_known_ticker_returns_clean_series(repo):
    history = repo.history("NVDA")
    assert len(history.closes) > 400
    assert not history.closes.isna().any()
    assert history.meta.currency == "USD"
    assert history.insufficient_history is False


def test_p1_index_is_dates_and_sorted(repo):
    closes = repo.history("MSFT").closes
    assert isinstance(closes.index, pd.DatetimeIndex)
    assert closes.index.is_monotonic_increasing


def test_p2_unresolvable_ticker_raises(repo):
    with pytest.raises(UnresolvedTicker) as exc:
        repo.history("XYZQ.FAKE")
    assert "XYZQ.FAKE" in str(exc.value)


def test_p2_never_returns_an_empty_series_for_unknown(repo):
    """An empty series would read as zero value rather than unknown value."""
    with pytest.raises(UnresolvedTicker):
        repo.history("NOT_A_TICKER")


@pytest.mark.parametrize(("ticker", "points"), [("SKHY", 22), ("SPCX", 40)])
def test_p3_short_history_flagged_but_returned(repo, ticker, points):
    history = repo.history(ticker)
    assert history.points == points
    assert points < MIN_HISTORY_DAYS
    assert history.insufficient_history is True
    assert len(history.closes) == points  # still usable for current value


def test_p3_long_history_not_flagged(repo):
    assert repo.history("GOOG").insufficient_history is False


# --- P4-P6: caching -----------------------------------------------------------------


class SpyFetcher:
    def __init__(self, series: pd.Series, meta: InstrumentMeta):
        self.series = series
        self.meta = meta
        self.calls: list[tuple[str, str]] = []

    def __call__(self, ticker: str, period: str):
        self.calls.append((ticker, period))
        return self.series, None, self.meta


@pytest.fixture
def spy():
    idx = pd.date_range("2026-01-01", periods=120, freq="D")
    series = pd.Series(range(1, 121), index=idx, dtype=float)
    meta = InstrumentMeta(ticker="AAA", currency="USD", name="Test", quote_type="EQUITY")
    return SpyFetcher(series, meta)


def test_p4_second_call_is_served_from_cache(spy):
    repo = CachedPriceRepository(fetcher=spy)
    repo.history("AAA")
    repo.history("AAA")
    assert len(spy.calls) == 1


def test_p5_cache_key_includes_the_period(spy):
    repo = CachedPriceRepository(fetcher=spy)
    repo.history("AAA", period="2y")
    repo.history("AAA", period="5y")
    assert spy.calls == [("AAA", "2y"), ("AAA", "5y")]


def test_p5_expired_entry_is_refetched(spy):
    clock = {"now": 1000.0}
    repo = CachedPriceRepository(fetcher=spy, ttl_seconds=60, clock=lambda: clock["now"])
    repo.history("AAA")
    clock["now"] += 61
    repo.history("AAA")
    assert len(spy.calls) == 2


def test_p5_unexpired_entry_is_not_refetched(spy):
    clock = {"now": 1000.0}
    repo = CachedPriceRepository(fetcher=spy, ttl_seconds=60, clock=lambda: clock["now"])
    repo.history("AAA")
    clock["now"] += 59
    repo.history("AAA")
    assert len(spy.calls) == 1


def test_p6_provider_error_surfaces_as_typed_error():
    def boom(ticker, period):
        raise OSError("connection reset")

    repo = CachedPriceRepository(fetcher=boom)
    with pytest.raises(PriceFetchError) as exc:
        repo.history("AAA")
    assert "AAA" in str(exc.value)


def test_p6_empty_provider_response_is_unresolved():
    def empty(ticker, period):
        return pd.Series(dtype=float), None, None

    repo = CachedPriceRepository(fetcher=empty)
    with pytest.raises(UnresolvedTicker):
        repo.history("AAA")


def test_failures_are_not_cached():
    calls = {"n": 0}

    def flaky(ticker, period):
        calls["n"] += 1
        raise OSError("transient")

    repo = CachedPriceRepository(fetcher=flaky)
    for _ in range(2):
        with pytest.raises(PriceFetchError):
            repo.history("AAA")
    assert calls["n"] == 2  # a transient failure must not poison the cache


# --- asset class --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("quote_type", "expected"),
    [("EQUITY", "EQUITY"), ("ETF", "ETF"), ("CRYPTOCURRENCY", "CRYPTO_ETP"), ("MUTUALFUND", "ETF")],
)
def test_infer_asset_class(quote_type, expected):
    assert infer_asset_class(quote_type) == expected


def test_infer_unknown_quote_type_is_none():
    assert infer_asset_class("INDEX") is None
    assert infer_asset_class(None) is None


def test_declared_asset_class_wins_over_inference():
    """The provider labels IGLN.L (physical gold ETC) as EQUITY, so the file must win."""
    resolved, inferred = resolve_asset_class(declared="ETC", quote_type="EQUITY")
    assert resolved == "ETC"
    assert inferred is False


def test_inference_used_only_when_column_absent():
    resolved, inferred = resolve_asset_class(declared=None, quote_type="ETF")
    assert resolved == "ETF"
    assert inferred is True


def test_inference_cannot_detect_etc(repo):
    """Documents the limitation: gold ETCs come back as EQUITY from the provider."""
    assert repo.history("IGLN.L").meta.quote_type == "EQUITY"
    assert infer_asset_class("EQUITY") != "ETC"
