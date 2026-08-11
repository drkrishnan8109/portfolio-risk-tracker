"""Live-wiring logic, exercised against a fake repository.

`src/market/live.py` is the only module that talks to a provider, but the decisions it
makes are real logic worth testing: which FX pairs to fetch, how `GBp` folds onto `GBP`,
and that a failing benchmark degrades to None rather than breaking the page.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.market.live import (
    benchmark_closes,
    currencies_for,
    fx_series_for,
)
from src.market.prices import UnresolvedTicker


class FakeRepo:
    def __init__(self, data: dict[str, tuple[pd.Series, str]]):
        self.data = data
        self.requested: list[str] = []

    def history(self, ticker: str, **kwargs):
        self.requested.append(ticker)
        if ticker not in self.data:
            raise UnresolvedTicker(ticker)
        closes, currency = self.data[ticker]

        class _H:
            def __init__(self, closes, currency):
                self.closes = closes
                self.meta = type("M", (), {"currency": currency})()

        return _H(closes, currency)


def series(n=5, value=1.0):
    return pd.Series([value] * n, index=pd.date_range("2026-01-01", periods=n, freq="D"))


@pytest.fixture
def repo_fake():
    return FakeRepo(
        {
            "NVDA": (series(), "USD"),
            "RHM.DE": (series(), "EUR"),
            "SGLN.L": (series(value=6000.0), "GBp"),
            "NESN.SW": (series(), "CHF"),
            "EURUSD=X": (series(value=1.15), "USD"),
            "EURGBP=X": (series(value=0.85), "GBP"),
            "EURCHF=X": (series(value=0.94), "CHF"),
            "^GSPC": (series(value=5000.0), "USD"),
        }
    )


def test_currencies_for_maps_each_ticker(repo_fake):
    found = currencies_for(repo_fake, ["NVDA", "RHM.DE", "SGLN.L"])
    assert found == {"NVDA": "USD", "RHM.DE": "EUR", "SGLN.L": "GBp"}


def test_currencies_for_skips_unresolvable_and_blank(repo_fake):
    found = currencies_for(repo_fake, ["NVDA", "", "NOPE"])
    assert found == {"NVDA": "USD"}


def test_fx_series_fetches_only_what_is_needed(repo_fake):
    fx = fx_series_for(repo_fake, {"USD", "EUR"})
    assert set(fx) == {"USD"}  # EUR is the pivot: no pair required


def test_fx_series_folds_pence_onto_pounds(repo_fake):
    """GBp and GBP must share a single fetch, not request a non-existent EURGBp=X."""
    fx = fx_series_for(repo_fake, {"GBp"})
    assert set(fx) == {"GBP"}
    assert "EURGBp=X" not in repo_fake.requested


def test_fx_series_deduplicates_pence_and_pounds(repo_fake):
    fx_series_for(repo_fake, {"GBp", "GBP"})
    assert repo_fake.requested.count("EURGBP=X") == 1


def test_fx_series_skips_an_unavailable_pair(repo_fake):
    fx = fx_series_for(repo_fake, {"USD", "JPY"})
    assert set(fx) == {"USD"}


def test_benchmark_converted_into_the_reporting_currency(repo_fake):
    fx = fx_series_for(repo_fake, {"USD"})
    closes = benchmark_closes(repo_fake, symbol="^GSPC", base_currency="EUR", fx_series=fx)
    assert closes.iloc[-1] == pytest.approx(5000.0 / 1.15)


def test_benchmark_in_the_base_currency_is_unconverted(repo_fake):
    closes = benchmark_closes(repo_fake, symbol="^GSPC", base_currency="USD", fx_series={})
    assert closes.iloc[-1] == pytest.approx(5000.0)


def test_missing_benchmark_returns_none_rather_than_raising(repo_fake):
    assert benchmark_closes(repo_fake, symbol="NOPE", base_currency="EUR", fx_series={}) is None


def test_benchmark_without_a_rate_returns_none(repo_fake):
    """Beta is optional; a missing rate must not break the whole page."""
    assert (
        benchmark_closes(repo_fake, symbol="^GSPC", base_currency="EUR", fx_series={}) is None
    )
