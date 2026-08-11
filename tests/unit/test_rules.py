"""Tests R1-R10 — the rule engine.

Every threshold gets below / at / above. The `at` case is not ceremony: the concentrated
fixture's largest position sits at 24.98%, so whether the rule is `>` or `>=` decides
its severity.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.risk.rules import (
    THRESHOLDS,
    Finding,
    RiskInputs,
    evaluate,
    find_high_correlation_pairs,
    severity_for,
    sort_findings,
)

# --- R1-R2: thresholds ----------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(THRESHOLDS))
def test_r2_every_threshold_grades_below_at_and_above(kind):
    high, medium = THRESHOLDS[kind]
    assert severity_for(medium - 1e-9, kind) is None, "below MEDIUM must not fire"
    assert severity_for(medium, kind) is None, "exactly at MEDIUM is not yet MEDIUM"
    assert severity_for(medium + 1e-9, kind) == "MEDIUM"
    assert severity_for(high, kind) == "MEDIUM", "exactly at HIGH is still MEDIUM"
    assert severity_for(high + 1e-9, kind) == "HIGH"


def test_r1_position_weight_boundary_is_strictly_greater_than():
    assert severity_for(0.249, "position_weight") == "MEDIUM"
    assert severity_for(0.250, "position_weight") == "MEDIUM"
    assert severity_for(0.251, "position_weight") == "HIGH"


def test_r1_the_2498_percent_case():
    """The concentrated fixture's largest position. Must be MEDIUM, not HIGH."""
    assert severity_for(0.2498, "position_weight") == "MEDIUM"


def test_r10_none_metric_produces_no_severity():
    for kind in THRESHOLDS:
        assert severity_for(None, kind) is None


def test_r10_none_metrics_produce_no_findings():
    findings = evaluate(RiskInputs())
    assert findings == []


# --- R3-R5: shape ---------------------------------------------------------------------


def test_r3_findings_sorted_high_then_medium():
    inputs = RiskInputs(
        weights=pd.Series({"AAA": 0.30, "BBB": 0.16, "CCC": 0.54}),
        top5_share=0.60,
    )
    findings = evaluate(inputs)
    severities = [f.severity for f in findings]
    assert severities == sorted(severities, key=lambda s: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[s])
    assert severities[0] == "HIGH"


def test_r3_sort_is_stable_for_equal_severity():
    a = Finding(id="a", kind="k", severity="MEDIUM", title="a", evidence={"v": 0.1})
    b = Finding(id="b", kind="k", severity="MEDIUM", title="b", evidence={"v": 0.9})
    assert [f.id for f in sort_findings([a, b])] == ["b", "a"]  # larger evidence first


def test_r4_evidence_contains_the_triggering_value():
    inputs = RiskInputs(weights=pd.Series({"NVDA": 0.30}))
    finding = evaluate(inputs)[0]
    assert finding.evidence["weight"] == pytest.approx(0.30)
    assert finding.threshold == THRESHOLDS["position_weight"][0]


def test_r4_every_finding_carries_evidence():
    inputs = RiskInputs(
        weights=pd.Series({"AAA": 0.40}),
        top5_share=0.80,
        largest_theme=("AI", 0.50),
        largest_currency=("USD", 0.90),
        portfolio_volatility=0.35,
        max_drawdown=0.45,
        avg_correlation=0.80,
        beta=1.5,
        crypto_allocation=0.25,
        below_200dma_weighted=0.70,
    )
    findings = evaluate(inputs)
    assert len(findings) >= 9
    for finding in findings:
        assert finding.evidence, f"{finding.id} has no evidence"
        assert finding.threshold is not None


def test_r5_finding_ids_are_unique():
    inputs = RiskInputs(
        weights=pd.Series({"AAA": 0.40, "BBB": 0.30, "CCC": 0.20}),
        top5_share=0.90,
        largest_sector=("Tech", 0.60),
        largest_theme=("AI", 0.60),
    )
    ids = [f.id for f in evaluate(inputs)]
    assert len(ids) == len(set(ids))


def test_position_findings_stop_at_the_first_clear_weight():
    inputs = RiskInputs(weights=pd.Series({"AAA": 0.30, "BBB": 0.05, "CCC": 0.65}))
    tickers = {t for f in evaluate(inputs) for t in f.affected_tickers}
    assert tickers == {"AAA", "CCC"}


# --- correlation pairs -----------------------------------------------------------------


def test_high_correlation_pairs_reported_once_each():
    matrix = pd.DataFrame(
        [[1.0, 0.95, 0.1], [0.95, 1.0, 0.2], [0.1, 0.2, 1.0]],
        index=["A", "B", "C"],
        columns=["A", "B", "C"],
    )
    pairs = find_high_correlation_pairs(matrix)
    assert pairs == [("A", "B", pytest.approx(0.95))]


def test_no_correlation_matrix_yields_no_pairs():
    assert find_high_correlation_pairs(None) == []


def test_correlated_pairs_become_a_finding():
    findings = evaluate(RiskInputs(high_correlation_pairs=[("A", "B", 0.91)]))
    assert findings[0].kind == "high_corr_pairs"
    assert findings[0].affected_tickers == ("A", "B")


def test_many_correlated_pairs_escalate_to_high():
    pairs = [(f"A{i}", f"B{i}", 0.9) for i in range(6)]
    assert evaluate(RiskInputs(high_correlation_pairs=pairs))[0].severity == "HIGH"


# --- R6-R8: the fixtures ---------------------------------------------------------------


def test_r6_balanced_portfolio_produces_no_high_findings(balanced_inputs):
    """The false-positive guard. A risk tool that cries wolf gets ignored."""
    findings = evaluate(balanced_inputs)
    high = [f for f in findings if f.severity == "HIGH"]
    assert high == [], f"unexpected HIGH findings: {[f.id for f in high]}"


def test_r7_concentrated_portfolio_produces_several_high_findings(speculative_inputs):
    findings = evaluate(speculative_inputs)
    high = [f for f in findings if f.severity == "HIGH"]
    assert len(high) >= 4
    assert "concentration.top5" in {f.id for f in high}


def test_r8_theme_finding_fires_where_sector_does_not(real_inputs):
    """Sector classification files thematic ETFs under Diversified and misses this."""
    findings = {f.id for f in evaluate(real_inputs)}
    assert "concentration.theme" in findings
    assert "concentration.sector" not in findings
