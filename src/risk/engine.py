"""Orchestration: a valued portfolio in, a complete analysis out.

The only module that knows the whole picture. Everything it calls is pure, so the
analysis is reproducible from the same inputs — no clock, no network, no globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.risk import concentration as conc
from src.risk import metrics as met
from src.risk import trends as tr
from src.risk.rules import Finding, RiskInputs, evaluate, find_high_correlation_pairs
from src.risk.valuation import ValuedPortfolio

CRYPTO_ASSET_CLASSES = {"CRYPTO_ETP", "CRYPTO"}


@dataclass
class Analysis:
    """Everything the UI renders."""

    portfolio: ValuedPortfolio
    weights: pd.Series
    position_metrics: dict[str, met.PositionMetrics] = field(default_factory=dict)
    trend_signals: dict[str, tr.TrendSignals] = field(default_factory=dict)
    correlation: pd.DataFrame | None = None
    by_asset_class: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    by_theme: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    by_currency: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    by_sector: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    inputs: RiskInputs = field(default_factory=RiskInputs)
    findings: list[Finding] = field(default_factory=list)

    # headline numbers
    total_value: float = 0.0
    total_cost_basis: float | None = None
    unrealised_pnl: float | None = None
    hhi: float | None = None
    effective_positions: float | None = None
    top5_share: float | None = None
    portfolio_volatility: float | None = None
    portfolio_beta: float | None = None
    portfolio_max_drawdown: float | None = None
    portfolio_var_95: float | None = None
    portfolio_cvar_95: float | None = None
    avg_correlation: float | None = None
    high_correlation_pairs: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def base_currency(self) -> str:
        return self.portfolio.base_currency

    @property
    def as_of(self) -> pd.Timestamp | None:
        """Latest price date behind this analysis, for the staleness caption."""
        return self.portfolio.as_of


def analyse(portfolio: ValuedPortfolio, *, benchmark_closes: pd.Series | None = None) -> Analysis:
    """Compute every metric and finding for a valued portfolio.

    Args:
        portfolio: Output of `src.risk.valuation.value_portfolio`.
        benchmark_closes: Benchmark price series, already in the reporting currency.
            Omit to skip beta.
    """
    weights = conc.weights(portfolio.holdings)
    benchmark_returns = (
        met.daily_returns(benchmark_closes) if benchmark_closes is not None else None
    )

    usable = {h.ticker: h for h in portfolio.holdings if h.usable_for_risk}
    returns = {t: met.daily_returns(h.closes_base) for t, h in usable.items()}

    position_metrics = {
        h.ticker: met.position_metrics(
            _AsHistory(h), benchmark_returns=benchmark_returns
        )
        for h in portfolio.holdings
        if h.priced and h.closes_base is not None
    }
    trend_signals = {
        h.ticker: tr.trend_signals(h.ticker, h.closes_base)
        for h in portfolio.holdings
        if h.priced and h.closes_base is not None
    }

    blended = met.portfolio_returns(returns, {t: float(weights.get(t, 0.0)) for t in returns})
    correlation = met.correlation_matrix(returns)
    pairs = find_high_correlation_pairs(correlation)

    avg_correlation = _average_pairwise_correlation(correlation)

    by_asset_class = conc.by_asset_class(portfolio.holdings)
    by_theme = conc.by_theme(portfolio.holdings)
    by_currency = conc.by_currency(portfolio.holdings)
    by_sector = conc.by_sector(portfolio.holdings)

    crypto = float(sum(by_asset_class.get(c, 0.0) for c in CRYPTO_ASSET_CLASSES))
    portfolio_volatility = met.annualised_volatility(blended) if not blended.empty else None
    portfolio_beta = (
        met.beta(blended, benchmark_returns)
        if not blended.empty and benchmark_returns is not None
        else None
    )
    equity_curve = (1 + blended).cumprod() if not blended.empty else pd.Series(dtype=float)
    portfolio_drawdown = met.max_drawdown(equity_curve) if not equity_curve.empty else None

    inputs = RiskInputs(
        weights=weights,
        top5_share=conc.top_n_share(weights, 5),
        largest_sector=conc.largest(by_sector),
        largest_theme=conc.largest(by_theme),
        largest_currency=conc.largest(by_currency),
        portfolio_volatility=portfolio_volatility,
        max_drawdown=portfolio_drawdown,
        avg_correlation=avg_correlation,
        high_correlation_pairs=pairs,
        beta=portfolio_beta,
        crypto_allocation=crypto or None,
        below_200dma_weighted=tr.weighted_share_below_200dma(
            list(trend_signals.values()), weights
        ),
    )

    return Analysis(
        portfolio=portfolio,
        weights=weights,
        position_metrics=position_metrics,
        trend_signals=trend_signals,
        correlation=correlation,
        by_asset_class=by_asset_class,
        by_theme=by_theme,
        by_currency=by_currency,
        by_sector=by_sector,
        inputs=inputs,
        findings=evaluate(inputs),
        total_value=portfolio.total_value,
        total_cost_basis=portfolio.total_cost_basis,
        unrealised_pnl=portfolio.unrealised_pnl,
        hhi=conc.hhi(weights),
        effective_positions=conc.effective_positions(weights),
        top5_share=inputs.top5_share,
        portfolio_volatility=portfolio_volatility,
        portfolio_beta=portfolio_beta,
        portfolio_max_drawdown=portfolio_drawdown,
        portfolio_var_95=met.historical_var(blended) if not blended.empty else None,
        portfolio_cvar_95=met.conditional_var(blended) if not blended.empty else None,
        avg_correlation=avg_correlation,
        high_correlation_pairs=pairs,
    )


def _average_pairwise_correlation(matrix: pd.DataFrame | None) -> float | None:
    """Mean of the off-diagonal entries.

    The matrix is symmetric with a unit diagonal, so only the upper triangle is read —
    including the diagonal would drag every average towards 1.0.
    """
    if matrix is None or len(matrix) < 2:
        return None
    values = matrix.to_numpy()
    rows, cols = np.triu_indices(len(values), k=1)
    upper = values[rows, cols]
    if upper.size == 0:
        return None
    return float(np.nanmean(upper))


@dataclass(frozen=True)
class _AsHistory:
    """Adapts a ValuedHolding to the shape `position_metrics` expects."""

    holding: object

    @property
    def ticker(self) -> str:
        return self.holding.ticker

    @property
    def closes(self) -> pd.Series:
        return self.holding.closes_base

    @property
    def insufficient_history(self) -> bool:
        return self.holding.insufficient_history

    @property
    def points(self) -> int:
        return self.holding.points
