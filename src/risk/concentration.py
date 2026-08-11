"""Concentration measures.

The single most important rule in this module: **unpriced holdings are excluded from
the weight denominator.** Including them at zero would understate every other position's
weight and hide concentration; excluding them entirely keeps the percentages honest
about the part of the portfolio we can actually measure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd

from src.risk.valuation import ValuedHolding

#: Grouping key -> how to read it off a holding, with the label used when absent.
UNKNOWN = "Unknown"


def weights(holdings: Sequence[ValuedHolding]) -> pd.Series:
    """Share of priced portfolio value per ticker, summing to 1.0.

    Unpriced holdings are omitted from both numerator and denominator.
    """
    priced = [h for h in holdings if h.priced and (h.value or 0) > 0]
    if not priced:
        return pd.Series(dtype=float)

    values = pd.Series(
        {h.ticker or (h.name or "unnamed"): float(h.value) for h in priced}, dtype=float
    )
    total = values.sum()
    if total <= 0:
        return pd.Series(dtype=float)
    return (values / total).sort_values(ascending=False)


def hhi(w: pd.Series) -> float | None:
    """Herfindahl-Hirschman Index: sum of squared weights.

    1/N for an equal-weight portfolio of N, 1.0 for a single position. Counts positions
    but ignores correlation, so read it beside average correlation and theme
    concentration.
    """
    if w.empty:
        return None
    return float((w**2).sum())


def effective_positions(w: pd.Series) -> float | None:
    """1 / HHI — how many equally-sized positions the portfolio behaves like."""
    index = hhi(w)
    if index is None or index <= 0:
        return None
    return 1.0 / index


def top_n_share(w: pd.Series, n: int = 5) -> float | None:
    """Combined weight of the n largest positions (all of them if fewer than n)."""
    if w.empty:
        return None
    return float(w.nlargest(n).sum())


def group_exposure(
    holdings: Sequence[ValuedHolding],
    key: Callable[[ValuedHolding], str | None],
    *,
    unknown_label: str = UNKNOWN,
    drop_unknown: bool = False,
) -> pd.Series:
    """Share of priced value per group, e.g. asset class, theme or currency.

    Args:
        holdings: The portfolio.
        key: Reads the grouping value off a holding.
        unknown_label: Bucket for holdings with no value for this key.
        drop_unknown: Omit that bucket entirely — used for theme, where an untagged
            holding should not dilute a real theme's share.
    """
    priced = [h for h in holdings if h.priced and (h.value or 0) > 0]
    if not priced:
        return pd.Series(dtype=float)

    totals: dict[str, float] = {}
    for holding in priced:
        label = key(holding) or unknown_label
        totals[label] = totals.get(label, 0.0) + float(holding.value)

    if drop_unknown:
        totals.pop(unknown_label, None)
    if not totals:
        return pd.Series(dtype=float)

    series = pd.Series(totals, dtype=float)
    denominator = series.sum()
    if denominator <= 0:
        return pd.Series(dtype=float)
    return (series / denominator).sort_values(ascending=False)


def by_asset_class(holdings: Sequence[ValuedHolding]) -> pd.Series:
    return group_exposure(holdings, lambda h: h.asset_class)


def by_theme(holdings: Sequence[ValuedHolding]) -> pd.Series:
    """Theme shares, ignoring untagged holdings so a real theme is not diluted."""
    return group_exposure(holdings, lambda h: h.theme, drop_unknown=True)


def by_currency(holdings: Sequence[ValuedHolding]) -> pd.Series:
    """Exposure by *pricing* currency, not the reporting currency."""
    return group_exposure(holdings, lambda h: h.currency)


def by_sector(holdings: Sequence[ValuedHolding]) -> pd.Series:
    return group_exposure(holdings, lambda h: h.sector, drop_unknown=True)


def largest(series: pd.Series) -> tuple[str, float] | None:
    """The biggest group and its share, or None for an empty breakdown."""
    if series.empty:
        return None
    return str(series.index[0]), float(series.iloc[0])
