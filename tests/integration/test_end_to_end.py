"""Tests E1-E5 — CSV in, findings out, with no network anywhere."""

from __future__ import annotations

import pytest

from src.ingest.loader import load_portfolio
from src.narrative.client import build_client
from src.narrative.explain import explain
from src.risk.concentration import by_asset_class, by_currency, by_theme, weights

FIXTURES = ["real_scalable.csv", "balanced_index.csv", "concentrated_speculative.csv"]


# --- E1: every fixture completes -------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_e1_fixture_runs_end_to_end(analyse_fixture, name):
    analysis = analyse_fixture(name)
    narrative = explain(analysis.findings, client=None)

    assert analysis.total_value > 0
    assert not analysis.weights.empty
    assert narrative.bullets
    assert len(narrative.bullets) == max(len(analysis.findings), 1)


@pytest.mark.parametrize("name", FIXTURES)
def test_e1_all_five_breakdowns_sum_to_one(analyse_fixture, name):
    analysis = analyse_fixture(name)
    for label, series in [
        ("holding", analysis.weights),
        ("asset class", analysis.by_asset_class),
        ("currency", analysis.by_currency),
    ]:
        assert series.sum() == pytest.approx(1.0, abs=1e-6), f"{name}: {label} does not sum to 1"

    if not analysis.by_theme.empty:
        assert analysis.by_theme.sum() == pytest.approx(1.0, abs=1e-6)


# --- E2-E3: the real portfolio ----------------------------------------------------------


def test_e2_real_portfolio_composition(real_analysis):
    portfolio = real_analysis.portfolio
    assert len(portfolio.holdings) == 19
    assert len(portfolio.priced) == 18
    assert len(portfolio.unpriced) == 1

    short = [h for h in portfolio.priced if h.insufficient_history]
    assert {h.ticker for h in short} == {"SKHY", "SPCX"}


def test_e2_short_history_positions_have_no_risk_metrics(real_analysis):
    for ticker in ("SKHY", "SPCX"):
        metrics = real_analysis.position_metrics[ticker]
        assert metrics.insufficient_history is True
        assert metrics.volatility is None


def test_e3_unresolved_holding_visible_but_unweighted(real_analysis):
    unpriced = real_analysis.portfolio.unpriced[0]
    assert unpriced.ticker == ""
    assert unpriced.cost_basis is not None and unpriced.cost_basis > 0
    assert unpriced.unavailable_reason == "no ticker supplied"
    assert "" not in real_analysis.weights.index
    assert len(real_analysis.weights) == 18


def test_e3_weights_still_sum_to_one_with_an_unpriced_holding(real_analysis):
    assert real_analysis.weights.sum() == pytest.approx(1.0)


def test_real_portfolio_headline_numbers(real_analysis):
    """Relative assertions only - the absolute figures are private and stay out of the repo."""
    basis = real_analysis.total_cost_basis
    assert basis is not None and basis > 0
    assert real_analysis.total_value > 0
    assert real_analysis.unrealised_pnl == pytest.approx(real_analysis.total_value - basis)
    # A plausible-value guard that does not disclose the amount.
    assert 0.5 < real_analysis.total_value / basis < 2.0


def test_real_portfolio_is_usd_dominated_despite_reporting_in_eur(real_analysis):
    assert real_analysis.base_currency == "EUR"
    assert by_currency(real_analysis.portfolio.holdings)["USD"] > 0.6


# --- the fixtures behave as designed ------------------------------------------------------


def test_balanced_portfolio_raises_no_high_findings(balanced_analysis):
    high = [f for f in balanced_analysis.findings if f.severity == "HIGH"]
    assert high == [], f"false positives: {[f.id for f in high]}"


def test_concentrated_portfolio_raises_several(speculative_analysis):
    high = [f for f in speculative_analysis.findings if f.severity == "HIGH"]
    assert len(high) >= 4


def test_theme_layer_beats_asset_class_for_crypto(speculative_analysis):
    holdings = speculative_analysis.portfolio.holdings
    assert by_theme(holdings)["Crypto"] > by_asset_class(holdings).get("CRYPTO_ETP", 0) * 2


def test_gbp_pence_holding_sized_correctly(balanced_analysis):
    assert 0.05 < balanced_analysis.weights["SGLN.L"] < 0.15


def test_blank_cost_basis_disables_pnl_but_not_analysis(speculative_analysis):
    assert speculative_analysis.total_cost_basis is None
    assert speculative_analysis.unrealised_pnl is None
    assert speculative_analysis.total_value > 0
    assert speculative_analysis.findings


# --- E4: determinism -----------------------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_e4_two_runs_produce_identical_results(analyse_fixture, name):
    first = analyse_fixture(name)
    second = analyse_fixture(name)

    assert first.total_value == second.total_value
    assert [f.id for f in first.findings] == [f.id for f in second.findings]
    assert [f.severity for f in first.findings] == [f.severity for f in second.findings]
    assert list(first.weights.round(12)) == list(second.weights.round(12))


# --- E5: round trip -------------------------------------------------------------------------


def test_e5_export_reimport_is_stable(real_analysis, tmp_path):
    """A portfolio the app exports must load back identically."""
    from src.store import write_portfolio_csv

    path = write_portfolio_csv(real_analysis.portfolio, tmp_path / "out.csv")
    reloaded = load_portfolio(path)

    original = {h.ticker: h for h in real_analysis.portfolio.holdings}
    assert len(reloaded.holdings) == len(original)
    for holding in reloaded.holdings:
        source = original[holding.ticker]
        assert holding.quantity == pytest.approx(source.quantity)
        if source.cost_basis is not None:
            assert holding.cost_basis == pytest.approx(source.cost_basis)
    assert reloaded.base_currency == real_analysis.base_currency


def test_e5_reimported_portfolio_reproduces_the_weights(
    real_analysis, tmp_path, repo, fx_series
):
    from src.market.fx import FxRates
    from src.risk.valuation import value_portfolio
    from src.store import write_portfolio_csv

    path = write_portfolio_csv(real_analysis.portfolio, tmp_path / "out.csv")
    reloaded = load_portfolio(path)
    revalued = value_portfolio(
        reloaded.holdings,
        repo=repo,
        base_currency=reloaded.base_currency,
        fx_series=fx_series,
        fx_rates=FxRates.from_series(fx_series, base=reloaded.base_currency),
    )
    assert weights(revalued.holdings).round(9).equals(real_analysis.weights.round(9))


# --- the guard itself ------------------------------------------------------------------------


def test_no_network_guard_is_active():
    """If this ever passes silently, every other test in the suite is suspect."""
    import socket

    from tests.conftest import NetworkAccessAttempted

    with pytest.raises(NetworkAccessAttempted):
        socket.create_connection(("example.com", 80))


def test_client_is_unavailable_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    status = build_client()
    assert status.available is False
    assert "ANTHROPIC_API_KEY" in status.reason
    assert status.mode_label == "Template narrative"


def test_analysis_exposes_the_fields_the_page_reads(real_analysis):
    """Guards the UI contract.

    A crash here is invisible to the pure-logic tests but takes the whole page down —
    which is exactly how `as_of` was missed the first time.
    """
    for attribute in (
        "base_currency",
        "as_of",
        "total_value",
        "total_cost_basis",
        "unrealised_pnl",
        "weights",
        "by_asset_class",
        "by_theme",
        "by_currency",
        "by_sector",
        "hhi",
        "effective_positions",
        "top5_share",
        "portfolio_volatility",
        "portfolio_beta",
        "portfolio_max_drawdown",
        "portfolio_var_95",
        "portfolio_cvar_95",
        "avg_correlation",
        "findings",
        "portfolio",
        "inputs",
    ):
        getattr(real_analysis, attribute)

    assert real_analysis.as_of == real_analysis.portfolio.as_of
    assert real_analysis.as_of is not None
