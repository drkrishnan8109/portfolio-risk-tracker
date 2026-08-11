"""Tests C1-C10 — weights, HHI and group exposure.

Fixture expectations use ranges rather than exact values: the price fixtures are
refreshable, and a test that breaks on a routine capture is noise. The ranges are still
tight enough to catch a real regression (a 100x GBp error, or unpriced rows leaking into
the denominator).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ingest.loader import load_portfolio
from src.market.fx import FxRates
from src.risk.concentration import (
    by_asset_class,
    by_currency,
    by_theme,
    effective_positions,
    group_exposure,
    hhi,
    largest,
    top_n_share,
    weights,
)
from src.risk.valuation import ValuedHolding, value_portfolio
from tests.conftest import fixture_path


def holding(ticker, value, **kwargs):
    return ValuedHolding(ticker=ticker, quantity=1.0, value=value, **kwargs)


@pytest.fixture
def valued(repo, fx_series):
    def _value(name: str):
        loaded = load_portfolio(fixture_path(name))
        return value_portfolio(
            loaded.holdings,
            repo=repo,
            base_currency=loaded.base_currency,
            fx_series=fx_series,
            fx_rates=FxRates.from_series(fx_series, base=loaded.base_currency),
        )

    return _value


# --- C1-C2: the denominator ----------------------------------------------------------


def test_c1_weights_sum_to_one():
    w = weights([holding("A", 100), holding("B", 300), holding("C", 600)])
    assert w.sum() == pytest.approx(1.0, abs=1e-9)


def test_c1_weights_are_sorted_descending():
    w = weights([holding("A", 100), holding("B", 300)])
    assert list(w.index) == ["B", "A"]


def test_c2_unpriced_holdings_are_excluded_from_the_denominator():
    """Including an unpriced row at zero would understate every other weight."""
    priced_only = weights([holding("A", 100), holding("B", 100)])
    with_unpriced = weights([holding("A", 100), holding("B", 100), holding("C", None)])
    pd.testing.assert_series_equal(priced_only, with_unpriced)
    assert with_unpriced["A"] == pytest.approx(0.5)


def test_c2_unresolved_holding_absent_from_weights():
    w = weights([holding("A", 100), holding("", None, name="SK Hynix GDR")])
    assert list(w.index) == ["A"]


def test_weights_of_an_all_unpriced_portfolio_is_empty():
    assert weights([holding("A", None)]).empty


# --- C3-C6: the indices --------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 4, 10])
def test_c3_c4_hhi_of_an_equal_weight_portfolio(n):
    w = weights([holding(f"T{i}", 100) for i in range(n)])
    assert hhi(w) == pytest.approx(1.0 / n)


def test_c4_single_position_hhi_is_one():
    assert hhi(weights([holding("A", 100)])) == pytest.approx(1.0)


def test_c5_effective_positions_is_the_reciprocal():
    w = weights([holding(f"T{i}", 100) for i in range(4)])
    assert effective_positions(w) == pytest.approx(4.0)


def test_c5_effective_positions_below_actual_when_uneven():
    w = weights([holding("A", 900), holding("B", 50), holding("C", 50)])
    assert effective_positions(w) < 3.0


def test_c6_top_n_of_a_smaller_portfolio_is_everything():
    w = weights([holding("A", 100), holding("B", 100), holding("C", 100)])
    assert top_n_share(w, 5) == pytest.approx(1.0)


def test_top_n_share_picks_the_largest():
    w = weights([holding("A", 700), holding("B", 200), holding("C", 100)])
    assert top_n_share(w, 2) == pytest.approx(0.9)


def test_indices_of_an_empty_portfolio_are_none():
    empty = pd.Series(dtype=float)
    assert hhi(empty) is None
    assert effective_positions(empty) is None
    assert top_n_share(empty) is None


# --- C7-C8: grouping -----------------------------------------------------------------


def test_c7_theme_groups_and_ignores_untagged():
    rows = [
        holding("A", 100, theme="AI"),
        holding("B", 100, theme="AI"),
        holding("C", 200, theme=None),
    ]
    themes = by_theme(rows)
    assert list(themes.index) == ["AI"]
    assert themes["AI"] == pytest.approx(1.0)  # untagged excluded from the denominator


def test_c7_untagged_holdings_do_not_dilute_a_theme():
    tagged_only = by_theme([holding("A", 100, theme="AI")])
    with_untagged = by_theme([holding("A", 100, theme="AI"), holding("B", 900)])
    assert tagged_only["AI"] == with_untagged["AI"] == pytest.approx(1.0)


def test_c8_currency_groups_by_pricing_currency():
    rows = [
        holding("A", 100, currency="USD"),
        holding("B", 300, currency="EUR"),
    ]
    exposure = by_currency(rows)
    assert exposure["EUR"] == pytest.approx(0.75)
    assert exposure["USD"] == pytest.approx(0.25)


def test_group_exposure_labels_missing_values_unknown():
    exposure = group_exposure([holding("A", 100)], lambda h: h.asset_class)
    assert list(exposure.index) == ["Unknown"]


def test_largest_returns_name_and_share():
    assert largest(by_currency([holding("A", 100, currency="USD")])) == ("USD", 1.0)
    assert largest(pd.Series(dtype=float)) is None


# --- C9-C10: the fixtures -------------------------------------------------------------


def test_c9_balanced_index_is_genuinely_diversified(valued):
    portfolio = valued("balanced_index.csv")
    w = weights(portfolio.holdings)
    assert len(w) == 11
    assert w.max() < 0.15, "no position should reach the MEDIUM concentration threshold"
    assert 0.07 <= hhi(w) <= 0.11
    assert effective_positions(w) > 9
    assert top_n_share(w, 5) < 0.55


def test_c9_gbp_pence_holding_is_not_inflated(valued):
    """SGLN.L quotes in pence; mishandled it would be ~900% of the portfolio."""
    portfolio = valued("balanced_index.csv")
    w = weights(portfolio.holdings)
    assert 0.05 < w["SGLN.L"] < 0.15


def test_c10_concentrated_portfolio_is_concentrated(valued):
    portfolio = valued("concentrated_speculative.csv")
    w = weights(portfolio.holdings)
    assert w.max() > 0.20
    assert top_n_share(w, 5) > 0.70
    assert effective_positions(w) < 9


def test_c10_theme_reveals_what_asset_class_hides(valued):
    """The argument for the theme layer, asserted on real numbers.

    IBIT alone is a modest crypto sleeve by asset class; once COIN, MSTR and RIOT are
    counted the portfolio is roughly a third bitcoin-linked.
    """
    portfolio = valued("concentrated_speculative.csv")
    crypto_by_class = by_asset_class(portfolio.holdings).get("CRYPTO_ETP", 0.0)
    crypto_by_theme = by_theme(portfolio.holdings).get("Crypto", 0.0)

    assert crypto_by_class < 0.15
    assert crypto_by_theme > 0.30
    assert crypto_by_theme > crypto_by_class * 2


def test_real_portfolio_excludes_the_unresolved_gdr(valued):
    portfolio = valued("real_scalable.csv")
    w = weights(portfolio.holdings)
    assert len(portfolio.holdings) == 19
    assert len(w) == 18, "the SK Hynix GDR has no ticker and must stay out of the weights"
    assert w.sum() == pytest.approx(1.0)


def test_real_portfolio_currency_split(valued):
    portfolio = valued("real_scalable.csv")
    exposure = by_currency(portfolio.holdings)
    assert set(exposure.index) >= {"USD", "EUR", "CHF"}
    assert exposure["USD"] > 0.5, "the portfolio reports in EUR but is USD-dominated"
