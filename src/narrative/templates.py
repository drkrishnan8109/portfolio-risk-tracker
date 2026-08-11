"""Deterministic bullet rendering.

The fallback whenever the model is unavailable, errors, or returns something ungrounded.
Every risk still reaches the user; only the prose quality drops. That property is what
lets the app treat the LLM as optional rather than load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.content.glossary import for_finding
from src.risk.rules import Finding

Severity = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class Bullet:
    severity: Severity
    text: str
    kind: str
    tickers: tuple[str, ...] = ()


NO_FINDINGS_TEXT = (
    "No thresholds were crossed. Concentration, volatility, drawdown and correlation "
    "all sit inside their usual ranges for this portfolio."
)


def render(findings: list[Finding]) -> list[Bullet]:
    """One bullet per finding: the measured statement, then how to interpret it."""
    if not findings:
        return [Bullet(severity="LOW", text=NO_FINDINGS_TEXT, kind="none")]

    bullets: list[Bullet] = []
    for finding in findings:
        guidance = for_finding(finding.kind).how_to_read
        bullets.append(
            Bullet(
                severity=finding.severity,
                text=f"{finding.title}. {guidance}",
                kind=finding.kind,
                tickers=finding.affected_tickers,
            )
        )
    return bullets
