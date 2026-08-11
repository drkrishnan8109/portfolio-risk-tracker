"""Risk statistics.

Conventions, chosen once so downstream code never has to ask:

* Losses are reported as **positive magnitudes** — a max drawdown of 0.5 is a 50% fall,
  a VaR of 0.03 is a 3% loss. Sign confusion is the classic bug in this kind of module.
* A statistic that cannot be computed returns **None**, never NaN and never 0.0. A zero
  would render as "no risk", which is the opposite of "unknown".
* Positions with too little history are excluded rather than estimated from a handful of
  observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Trading days per year, used to annualise daily statistics.
TRADING_DAYS = 252

#: Minimum overlapping observations before a two-series statistic is meaningful.
MIN_OVERLAP = 20

DEFAULT_CONFIDENCE = 0.95


def daily_returns(prices: pd.Series) -> pd.Series:
    """Simple daily returns, with non-finite values dropped.

    A zero price would make the next day's return infinite (FRCB trades at $0.0004),
    so anything non-finite is discarded rather than propagated.
    """
    returns = prices.astype(float).pct_change()
    returns = returns.replace([np.inf, -np.inf], np.nan)
    return returns.dropna()


def annualised_volatility(returns: pd.Series, *, periods: int = TRADING_DAYS) -> float:
    """Sample standard deviation of returns, annualised."""
    clean = returns.dropna()
    if len(clean) < 2:
        return 0.0
    return float(clean.std(ddof=1) * np.sqrt(periods))


def beta(returns: pd.Series, benchmark_returns: pd.Series) -> float | None:
    """Sensitivity of `returns` to `benchmark_returns`.

    Returns None when the benchmark has no variance or the two series barely overlap —
    both cases where a number would be meaningless rather than merely imprecise.
    """
    joined = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(joined) < MIN_OVERLAP:
        return None

    asset = joined.iloc[:, 0].to_numpy()
    market = joined.iloc[:, 1].to_numpy()
    variance = float(np.var(market, ddof=1))
    if variance <= 0:
        return None
    covariance = float(np.cov(asset, market, ddof=1)[0, 1])
    return covariance / variance


def max_drawdown(prices: pd.Series) -> float:
    """Largest peak-to-trough decline, as a positive fraction.

    Measured from the *running* peak, so a later, deeper fall from a higher high wins
    over an earlier shallow one.
    """
    clean = prices.dropna().astype(float)
    if len(clean) < 2:
        return 0.0
    running_peak = clean.cummax()
    drawdowns = (running_peak - clean) / running_peak.replace(0, np.nan)
    worst = drawdowns.max()
    return float(worst) if pd.notna(worst) else 0.0


def historical_var(
    returns: pd.Series, *, confidence: float = DEFAULT_CONFIDENCE
) -> float | None:
    """Historical Value at Risk as a positive loss fraction.

    The loss threshold breached on the worst (1 - confidence) share of days.
    """
    clean = returns.dropna()
    if clean.empty:
        return None
    quantile = float(np.quantile(clean.to_numpy(), 1.0 - confidence))
    return float(max(-quantile, 0.0))


def conditional_var(
    returns: pd.Series, *, confidence: float = DEFAULT_CONFIDENCE
) -> float | None:
    """Expected loss on days that breach VaR, as a positive fraction.

    Always at least VaR: it averages the tail rather than marking its edge.
    """
    clean = returns.dropna()
    if clean.empty:
        return None
    threshold = float(np.quantile(clean.to_numpy(), 1.0 - confidence))
    tail = clean[clean <= threshold]
    if tail.empty:
        return float(max(-threshold, 0.0))
    return float(max(-tail.mean(), 0.0))


def downside_deviation(
    returns: pd.Series, *, periods: int = TRADING_DAYS, threshold: float = 0.0
) -> float:
    """Annualised dispersion of returns below `threshold`.

    Upside moves are set to zero rather than dropped, so a volatile-but-rising series
    is not penalised for its gains.
    """
    clean = returns.dropna()
    if clean.empty:
        return 0.0
    shortfall = np.minimum(clean.to_numpy() - threshold, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)) * np.sqrt(periods))


def portfolio_returns(
    returns_by_ticker: Mapping[str, pd.Series], weights: Mapping[str, float]
) -> pd.Series:
    """Weighted blend of position returns, aligned on their shared dates.

    Weights are normalised, so callers may pass raw values.
    """
    usable = {t: r for t, r in returns_by_ticker.items() if t in weights and not r.dropna().empty}
    if not usable:
        return pd.Series(dtype=float)

    frame = pd.concat(usable, axis=1, join="inner").dropna()
    if frame.empty:
        return pd.Series(dtype=float)

    raw = np.array([weights[t] for t in frame.columns], dtype=float)
    total = raw.sum()
    if total <= 0:
        return pd.Series(dtype=float)
    return pd.Series(frame.to_numpy() @ (raw / total), index=frame.index)


def correlation_matrix(returns_by_ticker: Mapping[str, pd.Series]) -> pd.DataFrame | None:
    """Pairwise correlations, or None when there are fewer than two usable series."""
    usable = {t: r for t, r in returns_by_ticker.items() if len(r.dropna()) >= 2}
    if len(usable) < 2:
        return None
    frame = pd.concat(usable, axis=1, join="inner").dropna()
    if frame.shape[0] < MIN_OVERLAP or frame.shape[1] < 2:
        return None
    return frame.corr()


def simple_return(*, value: float | None, cost_basis: float | None) -> float | None:
    """Total return of a position against its cost basis.

    Returns None when the basis is missing or zero — an unknown or free position has no
    meaningful percentage return, and dividing would give infinity.
    """
    if value is None or cost_basis is None or cost_basis == 0:
        return None
    return (value - cost_basis) / cost_basis


@dataclass(frozen=True)
class PositionMetrics:
    """Per-position statistics. Every field is None when history is too short."""

    ticker: str
    insufficient_history: bool
    points: int
    volatility: float | None = None
    beta: float | None = None
    max_drawdown: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None
    downside_deviation: float | None = None


def position_metrics(history, *, benchmark_returns: pd.Series | None = None) -> PositionMetrics:
    """Compute every per-position statistic, or none of them.

    Args:
        history: A `PriceHistory`, ideally already converted to the reporting currency.
        benchmark_returns: Benchmark daily returns for beta. Omit to skip beta.
    """
    if history.insufficient_history:
        return PositionMetrics(
            ticker=history.ticker, insufficient_history=True, points=history.points
        )

    returns = daily_returns(history.closes)
    return PositionMetrics(
        ticker=history.ticker,
        insufficient_history=False,
        points=history.points,
        volatility=annualised_volatility(returns),
        beta=beta(returns, benchmark_returns) if benchmark_returns is not None else None,
        max_drawdown=max_drawdown(history.closes),
        var_95=historical_var(returns),
        cvar_95=conditional_var(returns),
        downside_deviation=downside_deviation(returns),
    )
