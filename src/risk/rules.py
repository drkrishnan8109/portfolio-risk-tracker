"""Metrics to findings.

Every threshold lives in `THRESHOLDS` so the whole risk policy is reviewable in one
place. All comparisons are strictly `>`: a value exactly at a threshold is the *lower*
severity. That matters — the concentrated fixture's largest position sits at 24.98%,
a hair under the 25% HIGH line.

A metric that could not be computed produces no finding. Silence means "unknown", never
"fine": a false LOW is worse than an absent bullet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

Severity = Literal["HIGH", "MEDIUM", "LOW"]

SEVERITY_ORDER: dict[Severity, int] = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

#: kind -> (high, medium). Reviewable risk policy, in one place.
THRESHOLDS: dict[str, tuple[float, float]] = {
    "position_weight": (0.25, 0.15),
    "top5_share": (0.70, 0.55),
    "sector_concentration": (0.40, 0.30),
    "theme_concentration": (0.45, 0.30),
    "currency_exposure": (0.80, 0.60),
    "portfolio_volatility": (0.30, 0.20),
    "max_drawdown": (0.40, 0.25),
    "avg_correlation": (0.75, 0.60),
    "beta": (1.4, 1.2),
    "crypto_allocation": (0.20, 0.10),
    "below_200dma": (0.60, 0.40),
}

#: Correlation above which two holdings are effectively one position held twice.
HIGH_CORRELATION = 0.8


@dataclass(frozen=True)
class Finding:
    """A single risk observation with the numbers that produced it."""

    id: str
    kind: str
    severity: Severity
    title: str
    evidence: dict[str, float]
    affected_tickers: tuple[str, ...] = ()
    threshold: float | None = None


@dataclass
class RiskInputs:
    """Everything the rule engine needs, already computed.

    Optional throughout: an absent metric is a metric that could not be computed, and
    produces no finding rather than a default.
    """

    weights: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    top5_share: float | None = None
    largest_sector: tuple[str, float] | None = None
    largest_theme: tuple[str, float] | None = None
    largest_currency: tuple[str, float] | None = None
    portfolio_volatility: float | None = None
    max_drawdown: float | None = None
    avg_correlation: float | None = None
    high_correlation_pairs: Sequence[tuple[str, str, float]] = ()
    beta: float | None = None
    crypto_allocation: float | None = None
    below_200dma_weighted: float | None = None


def severity_for(value: float | None, kind: str) -> Severity | None:
    """Grade a value against its thresholds, or None if it clears both.

    Comparisons are strictly greater-than, so a value sitting exactly on a threshold
    takes the lower severity.
    """
    if value is None:
        return None
    high, medium = THRESHOLDS[kind]
    if value > high:
        return "HIGH"
    if value > medium:
        return "MEDIUM"
    return None


def _pct(value: float) -> str:
    return f"{value:.1%}"


def evaluate(inputs: RiskInputs) -> list[Finding]:
    """Produce every triggered finding, most severe first."""
    findings: list[Finding] = []
    findings.extend(_position_findings(inputs.weights))
    findings.extend(_single_value_findings(inputs))
    findings.extend(_correlation_pair_findings(inputs.high_correlation_pairs))
    return sort_findings(findings)


def sort_findings(findings: Sequence[Finding]) -> list[Finding]:
    """HIGH first, then MEDIUM, then LOW; ties broken by evidence magnitude."""
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER[f.severity], -max(f.evidence.values(), default=0.0)),
    )


def _position_findings(weights: pd.Series) -> list[Finding]:
    findings: list[Finding] = []
    if weights.empty:
        return findings
    high, medium = THRESHOLDS["position_weight"]
    for ticker, weight in weights.sort_values(ascending=False).items():
        severity = severity_for(float(weight), "position_weight")
        if severity is None:
            break  # sorted desc - nothing below this crosses a threshold
        findings.append(
            Finding(
                id=f"concentration.position.{ticker}",
                kind="position_weight",
                severity=severity,
                title=f"{ticker} is {_pct(float(weight))} of the portfolio",
                evidence={"weight": float(weight)},
                affected_tickers=(str(ticker),),
                threshold=high if severity == "HIGH" else medium,
            )
        )
    return findings


def _single_value_findings(inputs: RiskInputs) -> list[Finding]:
    specs: list[tuple[str, str, float | None, str]] = [
        (
            "concentration.top5",
            "top5_share",
            inputs.top5_share,
            "Your five largest positions are {v} of the portfolio",
        ),
        (
            "volatility.portfolio",
            "portfolio_volatility",
            inputs.portfolio_volatility,
            "Portfolio volatility is {v} a year",
        ),
        (
            "drawdown.max",
            "max_drawdown",
            inputs.max_drawdown,
            "The portfolio fell {v} peak to trough in this window",
        ),
        (
            "diversification.correlation",
            "avg_correlation",
            inputs.avg_correlation,
            "Holdings move together: average correlation {v}",
        ),
        (
            "allocation.crypto",
            "crypto_allocation",
            inputs.crypto_allocation,
            "Crypto is {v} of the portfolio",
        ),
        (
            "trend.below_200dma",
            "below_200dma",
            inputs.below_200dma_weighted,
            "{v} of value trades below its 200-day average",
        ),
    ]

    findings: list[Finding] = []
    for finding_id, kind, value, template in specs:
        severity = severity_for(value, kind)
        if severity is None:
            continue
        high, medium = THRESHOLDS[kind]
        shown = f"{value:.2f}" if kind == "avg_correlation" else _pct(float(value))
        findings.append(
            Finding(
                id=finding_id,
                kind=kind,
                severity=severity,
                title=template.format(v=shown),
                evidence={kind: float(value)},
                threshold=high if severity == "HIGH" else medium,
            )
        )

    findings.extend(_beta_finding(inputs.beta))
    findings.extend(
        _group_finding(
            "concentration.sector", "sector_concentration", inputs.largest_sector, "sector"
        )
    )
    findings.extend(
        _group_finding("concentration.theme", "theme_concentration", inputs.largest_theme, "theme")
    )
    findings.extend(
        _group_finding(
            "currency.exposure", "currency_exposure", inputs.largest_currency, "currency"
        )
    )
    return findings


def _beta_finding(value: float | None) -> list[Finding]:
    severity = severity_for(value, "beta")
    if severity is None:
        return []
    high, medium = THRESHOLDS["beta"]
    return [
        Finding(
            id="market.beta",
            kind="beta",
            severity=severity,
            title=f"Portfolio beta is {value:.2f} — it amplifies market moves",
            evidence={"beta": float(value)},
            threshold=high if severity == "HIGH" else medium,
        )
    ]


def _group_finding(
    finding_id: str, kind: str, group: tuple[str, float] | None, noun: str
) -> list[Finding]:
    if group is None:
        return []
    label, share = group
    severity = severity_for(share, kind)
    if severity is None:
        return []
    high, medium = THRESHOLDS[kind]
    return [
        Finding(
            id=finding_id,
            kind=kind,
            severity=severity,
            title=f"{_pct(share)} of the portfolio sits in one {noun}: {label}",
            evidence={kind: float(share)},
            threshold=high if severity == "HIGH" else medium,
        )
    ]


def _correlation_pair_findings(
    pairs: Sequence[tuple[str, str, float]],
) -> list[Finding]:
    if not pairs:
        return []
    worst = max(float(c) for _, _, c in pairs)
    tickers = tuple(sorted({t for a, b, _ in pairs for t in (a, b)}))
    return [
        Finding(
            id="diversification.high_corr_pairs",
            kind="high_corr_pairs",
            severity="MEDIUM" if len(pairs) < 5 else "HIGH",
            title=(
                f"{len(pairs)} pair(s) of holdings move almost identically "
                f"(correlation up to {worst:.2f})"
            ),
            evidence={"pairs": float(len(pairs)), "max_correlation": worst},
            affected_tickers=tickers,
            threshold=HIGH_CORRELATION,
        )
    ]


def find_high_correlation_pairs(
    matrix: pd.DataFrame | None, *, threshold: float = HIGH_CORRELATION
) -> list[tuple[str, str, float]]:
    """Upper-triangle pairs above `threshold`, each reported once."""
    if matrix is None or matrix.empty:
        return []
    pairs: list[tuple[str, str, float]] = []
    columns = list(matrix.columns)
    for i, a in enumerate(columns):
        for b in columns[i + 1 :]:
            value = float(matrix.loc[a, b])
            if value > threshold:
                pairs.append((str(a), str(b), value))
    return sorted(pairs, key=lambda p: -p[2])
