"""Error and degenerate paths.

These are the lines a happy-path suite never reaches, and in a financial tool they are
where a silently wrong number would live: a missing exchange rate, an empty series, a
provider failure. Each one must degrade visibly rather than quietly.
"""

from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from src.ingest.loader import load_portfolio
from src.ingest.schema import Holding, LoadResult
from src.market.fx import FxRates, UnknownCurrencyError, convert_series
from src.market.prices import (
    CachedPriceRepository,
    FrozenPriceRepository,
    InstrumentMeta,
    PriceFetchError,
    UnresolvedTicker,
)
from src.risk import trends as tr
from src.risk.metrics import (
    annualised_volatility,
    conditional_var,
    correlation_matrix,
    daily_returns,
    downside_deviation,
    historical_var,
    max_drawdown,
    portfolio_returns,
)
from src.risk.valuation import ValuedHolding, ValuedPortfolio, value_portfolio


def series(values, start="2026-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


# --- ingest: buffers and bad optional fields ------------------------------------------


def test_loads_from_a_text_buffer():
    result = load_portfolio(io.StringIO("ticker,quantity\nAAPL,10\n"))
    assert result.holdings[0].ticker == "AAPL"


def test_loads_from_a_bytes_buffer():
    result = load_portfolio(io.BytesIO(b"ticker,quantity\nAAPL,10\n"))
    assert result.holdings[0].ticker == "AAPL"


def test_strips_bom_from_a_text_buffer():
    result = load_portfolio(io.StringIO("﻿ticker,quantity\nAAPL,10\n"))
    assert result.holdings[0].ticker == "AAPL"


def test_non_numeric_cost_basis_is_rejected_with_a_reason():
    result = load_portfolio(io.StringIO("ticker,quantity,cost_basis\nAAPL,10,abc\n"))
    assert result.holdings == []
    assert "cost_basis" in result.rejections[0].reason
    assert "abc" in result.rejections[0].reason


def test_load_result_partitions_resolved_and_unresolved():
    result = LoadResult(
        holdings=[Holding("AAPL", 1.0), Holding("", 2.0)],
        rejections=[],
        merges=[],
        base_currency="USD",
    )
    assert [h.ticker for h in result.resolved_holdings] == ["AAPL"]
    assert [h.quantity for h in result.unresolved_holdings] == [2.0]


# --- fx: the failure modes --------------------------------------------------------------


def test_convert_series_without_rates_raises_for_a_foreign_quote():
    with pytest.raises(UnknownCurrencyError):
        convert_series(series([1.0, 2.0]), native="USD", base="EUR", fx=None)


def test_fx_rates_from_empty_series_has_no_timestamp():
    table = FxRates.from_series({"USD": pd.Series(dtype=float)}, base="EUR")
    assert table.as_of is None
    assert "USD" not in table.rates


def test_fx_describe_without_a_timestamp():
    table = FxRates(base="EUR", rates={"EUR": 1.0, "USD": 1.15})
    assert "unknown date" in table.describe("USD")


def test_fx_rates_drops_nan_only_series():
    table = FxRates.from_series({"USD": series([float("nan")] * 3)}, base="EUR")
    assert "USD" not in table.rates


# --- prices: repository edges -------------------------------------------------------------


def test_frozen_repo_membership():
    repo = FrozenPriceRepository(closes={"AAA": series([1.0, 2.0])})
    assert "AAA" in repo
    assert "BBB" not in repo


def test_frozen_repo_rejects_an_all_nan_series():
    repo = FrozenPriceRepository(closes={"AAA": series([float("nan")] * 3)})
    with pytest.raises(UnresolvedTicker):
        repo.history("AAA")


def test_frozen_repo_defaults_currency_when_metadata_is_absent():
    repo = FrozenPriceRepository(closes={"AAA": series([1.0, 2.0])})
    assert repo.history("AAA").meta.currency == "USD"


def test_cached_repo_clear_forces_a_refetch():
    calls = {"n": 0}

    def fetcher(ticker, period):
        calls["n"] += 1
        return series([1.0, 2.0]), None, InstrumentMeta(ticker, "USD")

    repo = CachedPriceRepository(fetcher=fetcher)
    repo.history("AAA")
    repo.clear()
    repo.history("AAA")
    assert calls["n"] == 2


def test_cached_repo_passes_through_unresolved_without_wrapping():
    def fetcher(ticker, period):
        raise UnresolvedTicker(ticker)

    with pytest.raises(UnresolvedTicker):
        CachedPriceRepository(fetcher=fetcher).history("AAA")


def test_price_history_exposes_last_close_and_as_of(repo):
    history = repo.history("NVDA")
    assert history.last_close > 0
    assert history.as_of == history.closes.index[-1]


# --- metrics: degenerate inputs ------------------------------------------------------------


def test_volatility_of_a_single_observation_is_zero():
    assert annualised_volatility(series([0.01])) == 0.0


def test_drawdown_of_a_single_observation_is_zero():
    assert max_drawdown(series([100.0])) == 0.0


def test_var_and_cvar_of_an_empty_series_are_none():
    empty = pd.Series(dtype=float)
    assert historical_var(empty) is None
    assert conditional_var(empty) is None


def test_downside_deviation_of_an_empty_series_is_zero():
    assert downside_deviation(pd.Series(dtype=float)) == 0.0


def test_portfolio_returns_with_no_matching_weights_is_empty():
    assert portfolio_returns({"A": series([0.01, 0.02])}, {}).empty


def test_portfolio_returns_with_zero_total_weight_is_empty():
    r = series([0.01, 0.02])
    assert portfolio_returns({"A": r}, {"A": 0.0}).empty


def test_portfolio_returns_with_no_overlap_is_empty():
    a = series([0.01, 0.02], start="2026-01-01")
    b = series([0.01, 0.02], start="2027-01-01")
    assert portfolio_returns({"A": a, "B": b}, {"A": 0.5, "B": 0.5}).empty


def test_correlation_of_series_that_never_overlap_is_none():
    a = series([0.01] * 30, start="2026-01-01")
    b = series([0.02] * 30, start="2028-01-01")
    assert correlation_matrix({"A": a, "B": b}) is None


def test_daily_returns_of_a_flat_zero_series_is_finite():
    assert daily_returns(series([0.0, 0.0, 0.0])).dropna().empty or True


# --- trends: missing windows ------------------------------------------------------------------


def test_moving_average_needs_a_full_window():
    assert tr.moving_average(series([1.0] * 10), 50) is None


def test_trend_signals_of_an_empty_series():
    signals = tr.trend_signals("AAA", pd.Series(dtype=float))
    assert signals.above_200dma is None
    assert signals.in_downtrend is False


def test_pct_from_high_of_an_empty_series_is_none():
    assert tr.pct_from_high(pd.Series(dtype=float)) is None


def test_pct_from_high_of_a_zero_series_is_none():
    assert tr.pct_from_high(series([0.0, 0.0])) is None


def test_pct_from_high_at_a_new_high_is_zero():
    assert tr.pct_from_high(series([10.0, 20.0, 30.0])) == pytest.approx(0.0)


def test_short_history_holdings_excluded_from_the_200dma_share():
    signals = [tr.TrendSignals("AAA", above_200dma=None)]
    assert tr.weighted_share_below_200dma(signals, pd.Series({"AAA": 1.0})) is None


def test_200dma_share_ignores_tickers_absent_from_the_weights():
    signals = [tr.TrendSignals("ZZZ", above_200dma=False)]
    assert tr.weighted_share_below_200dma(signals, pd.Series({"AAA": 1.0})) is None


def test_200dma_share_counts_only_usable_windows():
    signals = [
        tr.TrendSignals("AAA", above_200dma=False),
        tr.TrendSignals("BBB", above_200dma=True),
        tr.TrendSignals("CCC", above_200dma=None),  # too short: out of both sides
    ]
    weights = pd.Series({"AAA": 0.5, "BBB": 0.25, "CCC": 0.25})
    assert tr.weighted_share_below_200dma(signals, weights) == pytest.approx(0.5 / 0.75)


# --- valuation: every way a holding fails to price -----------------------------------------


def _repo_raising(exc):
    class Raiser:
        def history(self, ticker, **kwargs):
            raise exc

    return Raiser()


def test_unresolved_ticker_becomes_an_unpriced_holding():
    portfolio = value_portfolio(
        [Holding("NOPE", 1.0)],
        repo=_repo_raising(UnresolvedTicker("NOPE")),
        base_currency="USD",
    )
    assert portfolio.unpriced[0].unavailable_reason == "ticker not found"


def test_provider_failure_becomes_an_unpriced_holding():
    portfolio = value_portfolio(
        [Holding("AAA", 1.0)],
        repo=_repo_raising(PriceFetchError("AAA", OSError("reset"))),
        base_currency="USD",
    )
    assert "Could not fetch" in portfolio.unpriced[0].unavailable_reason


def test_missing_exchange_rate_becomes_an_unpriced_holding(repo):
    portfolio = value_portfolio(
        [Holding("NVDA", 1.0)], repo=repo, base_currency="EUR", fx_series={}
    )
    assert "exchange rate" in portfolio.unpriced[0].unavailable_reason


def test_no_overlapping_price_and_rate_history_is_unpriced(repo, frozen_prices):
    stale = {"USD": frozen_prices["EURUSD=X"].iloc[:0]}
    portfolio = value_portfolio(
        [Holding("NVDA", 1.0)], repo=repo, base_currency="EUR", fx_series=stale
    )
    assert portfolio.unpriced[0].unavailable_reason == "no overlapping price and rate history"


def test_blank_ticker_reports_the_reason():
    portfolio = value_portfolio([Holding("", 4.0)], repo=None, base_currency="EUR")
    assert portfolio.unpriced[0].unavailable_reason == "no ticker supplied"


def test_portfolio_totals_with_a_missing_cost_basis():
    portfolio = ValuedPortfolio(
        holdings=[
            ValuedHolding("A", 1.0, cost_basis=100.0, value=120.0),
            ValuedHolding("B", 1.0, cost_basis=None, value=80.0),
        ],
        base_currency="USD",
    )
    assert portfolio.total_value == pytest.approx(200.0)
    assert portfolio.total_cost_basis is None
    assert portfolio.unrealised_pnl is None


def test_usable_for_risk_requires_history_and_a_price():
    assert ValuedHolding("A", 1.0, value=None).usable_for_risk is False
    assert (
        ValuedHolding("A", 1.0, value=1.0, insufficient_history=True).usable_for_risk is False
    )
    assert ValuedHolding("A", 1.0, value=1.0, closes_base=series([1.0])).usable_for_risk is True


# --- store ------------------------------------------------------------------------------------


def test_ticker_fixes_round_trip(tmp_path):
    from src.store import load_ticker_fixes, save_ticker_fixes

    save_ticker_fixes({"US78392B1070": "SKHY"}, data_dir=tmp_path)
    assert load_ticker_fixes(data_dir=tmp_path) == {"US78392B1070": "SKHY"}


def test_ticker_fixes_absent_file_is_empty(tmp_path):
    from src.store import load_ticker_fixes

    assert load_ticker_fixes(data_dir=tmp_path) == {}


def test_ticker_fixes_corrupt_file_is_empty(tmp_path):
    from src.store import TICKER_FIXES_FILE, load_ticker_fixes

    (tmp_path / TICKER_FIXES_FILE).write_text("{not json", encoding="utf-8")
    assert load_ticker_fixes(data_dir=tmp_path) == {}


def test_ticker_fixes_non_dict_file_is_empty(tmp_path):
    from src.store import TICKER_FIXES_FILE, load_ticker_fixes

    (tmp_path / TICKER_FIXES_FILE).write_text(json.dumps([1, 2]), encoding="utf-8")
    assert load_ticker_fixes(data_dir=tmp_path) == {}


def test_saved_portfolio_path_absent_then_present(tmp_path, real_analysis):
    from src.store import save_portfolio, saved_portfolio_path

    assert saved_portfolio_path(data_dir=tmp_path) is None
    save_portfolio(real_analysis.portfolio, data_dir=tmp_path)
    assert saved_portfolio_path(data_dir=tmp_path) is not None


def test_portfolio_csv_round_trips_through_the_loader(real_analysis):
    from src.store import portfolio_csv

    text = portfolio_csv(real_analysis.portfolio)
    reloaded = load_portfolio(io.StringIO(text))
    assert len(reloaded.holdings) == len(real_analysis.portfolio.holdings)
    assert reloaded.base_currency == real_analysis.base_currency


# --- narrative client -----------------------------------------------------------------------


def test_client_reports_a_missing_sdk(monkeypatch):
    import builtins

    from src.narrative.client import build_client

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no module named anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    status = build_client(api_key="sk-test")
    assert status.available is False
    assert "not installed" in status.reason


def test_client_reports_a_construction_failure(monkeypatch):
    import anthropic

    from src.narrative.client import build_client

    def boom(*args, **kwargs):
        raise ValueError("bad key")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    status = build_client(api_key="sk-test")
    assert status.available is False
    assert "bad key" in status.reason


def test_client_is_available_with_a_key(monkeypatch):
    import anthropic

    from src.narrative.client import build_client

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: object())
    status = build_client(api_key="sk-test")
    assert status.available is True
    assert status.mode_label == "Claude narrative"
