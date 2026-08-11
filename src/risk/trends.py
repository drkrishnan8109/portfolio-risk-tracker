"""Trend context: moving averages and distance from the 52-week high.

These are descriptive, not predictive. They answer "where is this trading relative to its
own recent history", which is context for the concentration and volatility findings
rather than a signal in its own right.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

SHORT_WINDOW = 50
LONG_WINDOW = 200
YEAR_WINDOW = 252


@dataclass(frozen=True)
class TrendSignals:
    ticker: str
    above_50dma: bool | None = None
    above_200dma: bool | None = None
    pct_from_52w_high: float | None = None

    @property
    def in_downtrend(self) -> bool:
        return self.above_200dma is False


def moving_average(prices: pd.Series, window: int) -> float | None:
    """Mean of the last `window` observations, or None if there are too few."""
    clean = prices.dropna()
    if len(clean) < window:
        return None
    return float(clean.iloc[-window:].mean())


def pct_from_high(prices: pd.Series, window: int = YEAR_WINDOW) -> float | None:
    """Current price relative to its rolling-window high, as a negative fraction.

    -0.30 means 30% below the high. Returns 0.0 when at a new high.
    """
    clean = prices.dropna()
    if clean.empty:
        return None
    recent = clean.iloc[-window:] if len(clean) > window else clean
    peak = float(recent.max())
    if peak <= 0:
        return None
    return float(recent.iloc[-1]) / peak - 1.0


def trend_signals(ticker: str, prices: pd.Series) -> TrendSignals:
    """All trend measures for one holding. Missing windows stay None."""
    clean = prices.dropna()
    if clean.empty:
        return TrendSignals(ticker=ticker)

    last = float(clean.iloc[-1])
    ma_50 = moving_average(clean, SHORT_WINDOW)
    ma_200 = moving_average(clean, LONG_WINDOW)
    return TrendSignals(
        ticker=ticker,
        above_50dma=None if ma_50 is None else last > ma_50,
        above_200dma=None if ma_200 is None else last > ma_200,
        pct_from_52w_high=pct_from_high(clean),
    )


def weighted_share_below_200dma(
    signals: Sequence[TrendSignals], weights: pd.Series
) -> float | None:
    """Portfolio value trading below its 200-day average.

    Only holdings with a usable 200-day window count, in both numerator and denominator,
    so a portfolio of recent listings does not read as 0% weakness.
    """
    usable = [s for s in signals if s.above_200dma is not None and s.ticker in weights.index]
    if not usable:
        return None
    denominator = sum(float(weights[s.ticker]) for s in usable)
    if denominator <= 0:
        return None
    below = sum(float(weights[s.ticker]) for s in usable if s.above_200dma is False)
    return below / denominator
