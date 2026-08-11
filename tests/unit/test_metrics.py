"""Tests M1-M14 — the risk numbers.

Expectations are hand-computed from small series rather than derived from the
implementation, so a failure points at the formula rather than at a data source.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.risk.metrics import (
    TRADING_DAYS,
    PositionMetrics,
    annualised_volatility,
    beta,
    conditional_var,
    correlation_matrix,
    daily_returns,
    downside_deviation,
    historical_var,
    max_drawdown,
    portfolio_returns,
    position_metrics,
    simple_return,
)


def series(values, start="2026-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


# --- M1-M3: volatility ---------------------------------------------------------------


def test_m1_annualised_volatility_hand_computed():
    returns = series([0.01, -0.01, 0.02, -0.02])
    # sample std = sqrt(0.001 / 3) = 0.0182574186; x sqrt(252) = 0.2898274
    assert annualised_volatility(returns) == pytest.approx(0.2898274, rel=1e-6)


def test_m1_scales_with_sqrt_of_trading_days():
    returns = series([0.01, -0.01, 0.02, -0.02])
    assert annualised_volatility(returns) == pytest.approx(
        float(returns.std(ddof=1)) * np.sqrt(TRADING_DAYS)
    )


def test_m1_constant_returns_have_zero_volatility():
    assert annualised_volatility(series([0.01] * 10)) == pytest.approx(0.0)


def test_m2_perfectly_correlated_assets_give_the_weighted_average():
    r = series([0.01, -0.02, 0.03, -0.01, 0.02])
    combined = portfolio_returns({"A": r, "B": r}, {"A": 0.6, "B": 0.4})
    assert annualised_volatility(combined) == pytest.approx(annualised_volatility(r))


def test_m3_uncorrelated_assets_reduce_portfolio_volatility():
    a = series([0.02, -0.02, 0.02, -0.02, 0.02, -0.02, 0.02, -0.02])
    b = series([0.02, 0.02, -0.02, -0.02, 0.02, 0.02, -0.02, -0.02])
    assert abs(float(np.corrcoef(a, b)[0, 1])) < 1e-12  # orthogonal by construction

    combined = portfolio_returns({"A": a, "B": b}, {"A": 0.5, "B": 0.5})
    average = 0.5 * annualised_volatility(a) + 0.5 * annualised_volatility(b)
    assert annualised_volatility(combined) < average


def test_portfolio_returns_weights_are_normalised():
    r = series([0.01, 0.02, -0.01])
    a = portfolio_returns({"A": r, "B": r}, {"A": 1.0, "B": 1.0})
    b = portfolio_returns({"A": r, "B": r}, {"A": 0.5, "B": 0.5})
    pd.testing.assert_series_equal(a, b)


def test_portfolio_returns_align_on_shared_dates():
    a = series([0.01, 0.02, 0.03], start="2026-01-01")
    b = series([0.01, 0.02, 0.03], start="2026-01-02")
    combined = portfolio_returns({"A": a, "B": b}, {"A": 0.5, "B": 0.5})
    assert len(combined) == 2  # only the overlapping days


# --- M4-M5: beta ---------------------------------------------------------------------


#: Long enough to clear MIN_OVERLAP; beta on a handful of days is noise, not a number.
MARKET = series([0.01, -0.02, 0.03, -0.01, 0.015] * 6)


def test_m4_beta_against_itself_is_one():
    assert beta(MARKET, MARKET) == pytest.approx(1.0)


def test_m5_beta_of_a_doubled_series_is_two():
    assert beta(MARKET * 2, MARKET) == pytest.approx(2.0)


def test_beta_of_an_inverse_series_is_negative_one():
    assert beta(-MARKET, MARKET) == pytest.approx(-1.0)


def test_beta_is_none_when_benchmark_has_no_variance():
    flat = series([0.0] * 30)
    assert beta(series([0.01, 0.02, 0.0, -0.01, 0.03] * 6), flat) is None


def test_beta_is_none_without_enough_overlap():
    a = series([0.01, 0.02], start="2026-01-01")
    b = series([0.01, 0.02], start="2026-06-01")
    assert beta(a, b) is None


# --- M6-M7: drawdown -----------------------------------------------------------------


def test_m6_monotonic_rise_has_no_drawdown():
    assert max_drawdown(series([100, 101, 102, 103])) == pytest.approx(0.0)


def test_m7_known_peak_to_trough():
    # peak 120 -> trough 60 is a 50% fall
    assert max_drawdown(series([100, 120, 60, 80])) == pytest.approx(0.5)


def test_m7_drawdown_measured_from_the_running_peak_not_the_start():
    # the 90 -> 45 leg is deeper (50%) than 100 -> 90 (10%)
    assert max_drawdown(series([100, 90, 180, 90])) == pytest.approx(0.5)


def test_drawdown_is_reported_as_a_positive_fraction():
    assert max_drawdown(series([100, 50])) > 0


# --- M8-M9: tail risk ----------------------------------------------------------------


def test_m8_var_never_exceeds_cvar_on_a_known_series():
    returns = series([-0.10, -0.05, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    assert historical_var(returns) <= conditional_var(returns)


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
        min_size=20,
        max_size=200,
    )
)
def test_m8_var_le_cvar_property(values):
    returns = series(values)
    var = historical_var(returns)
    cvar = conditional_var(returns)
    if var is not None and cvar is not None:
        assert cvar >= var - 1e-12


def test_var_is_a_positive_loss_magnitude():
    # Five losing days in forty puts the 5th percentile firmly in loss territory.
    returns = series([-0.10] * 5 + [0.01] * 35)
    assert historical_var(returns) == pytest.approx(0.10, rel=1e-6)


def test_var_is_zero_when_even_the_bad_tail_is_profitable():
    """One bad day in twenty leaves the 5th percentile positive, so VaR clamps to 0."""
    assert historical_var(series([-0.10] + [0.01] * 19)) == 0.0


def test_m9_all_positive_returns_have_zero_downside_deviation():
    assert downside_deviation(series([0.01, 0.02, 0.03])) == pytest.approx(0.0)


def test_downside_deviation_ignores_upside():
    mixed = series([-0.02, 0.50, -0.02, 0.50])
    only_down = series([-0.02, 0.0, -0.02, 0.0])
    assert downside_deviation(mixed) == pytest.approx(downside_deviation(only_down))


# --- M10-M12: matrices and degenerate inputs -----------------------------------------


def test_m10_correlation_matrix_is_symmetric_with_unit_diagonal():
    a = series([0.01, -0.02, 0.03, -0.01, 0.02] * 6)
    b = series([0.02, -0.01, 0.01, -0.03, 0.01] * 6)
    matrix = correlation_matrix({"A": a, "B": b})
    assert np.allclose(np.diag(matrix.to_numpy()), 1.0)
    assert np.allclose(matrix.to_numpy(), matrix.to_numpy().T)


def test_m11_single_position_has_no_correlation_matrix():
    assert correlation_matrix({"A": series([0.01, 0.02, -0.01] * 10)}) is None


def test_m11_too_little_overlap_has_no_correlation_matrix():
    a = series([0.01, -0.02, 0.03])
    b = series([0.02, -0.01, 0.01])
    assert correlation_matrix({"A": a, "B": b}) is None


def test_m11_empty_input_has_no_correlation_matrix():
    assert correlation_matrix({}) is None


def test_m12_constant_price_series_is_safe():
    prices = series([50.0] * 100)
    returns = daily_returns(prices)
    assert annualised_volatility(returns) == pytest.approx(0.0)
    assert max_drawdown(prices) == pytest.approx(0.0)
    assert beta(returns, returns) is None  # zero variance benchmark


def test_m12_no_division_by_zero_on_a_zero_price():
    prices = series([10.0, 0.0, 5.0])
    returns = daily_returns(prices)
    assert np.isfinite(returns.dropna()).all() or returns.dropna().empty


# --- M13: the FRCB case ---------------------------------------------------------------


def test_m13_total_loss_position_returns_minus_one():
    """FRCB: EUR 1,065.19 cost basis now worth EUR 0.0128."""
    assert simple_return(value=0.0128, cost_basis=1065.19) == pytest.approx(-0.99999, abs=1e-4)


def test_m13_zero_cost_basis_is_none_not_infinity():
    result = simple_return(value=100.0, cost_basis=0.0)
    assert result is None


def test_m13_missing_cost_basis_is_none():
    assert simple_return(value=100.0, cost_basis=None) is None


def test_m13_frcb_price_series_produces_finite_metrics(repo):
    history = repo.history("FRCB")
    returns = daily_returns(history.closes)
    assert np.isfinite(annualised_volatility(returns))
    assert 0.0 <= max_drawdown(history.closes) <= 1.0


# --- M14: insufficient history --------------------------------------------------------


@pytest.mark.parametrize("ticker", ["SKHY", "SPCX"])
def test_m14_short_history_positions_report_no_metrics(repo, ticker):
    metrics = position_metrics(repo.history(ticker))
    assert isinstance(metrics, PositionMetrics)
    assert metrics.insufficient_history is True
    assert metrics.volatility is None
    assert metrics.beta is None
    assert metrics.max_drawdown is None
    assert metrics.var_95 is None


def test_m14_long_history_positions_report_metrics(repo):
    benchmark = daily_returns(repo.history("^GSPC").closes)
    metrics = position_metrics(repo.history("NVDA"), benchmark_returns=benchmark)
    assert metrics.insufficient_history is False
    assert metrics.volatility is not None and metrics.volatility > 0
    assert metrics.beta is not None
    assert 0.0 <= metrics.max_drawdown <= 1.0
