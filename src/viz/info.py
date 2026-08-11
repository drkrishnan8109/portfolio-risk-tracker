"""The ⓘ affordance.

Every number the app renders gets its explanation from here. `help_for` raises on an
unregistered key, so a metric shipped without an explanation fails loudly rather than
appearing as a bare number.
"""

from __future__ import annotations

from src.content.glossary import entry, for_finding, tooltip
from src.risk.rules import Finding


def help_for(key: str) -> str:
    """Markdown for a Streamlit `help=` argument. Raises on an unknown key."""
    return tooltip(key)


def label_for(key: str) -> str:
    return entry(key).label


def finding_help(finding: Finding) -> str:
    """Explanation for one risk bullet: what it measures, plus what tripped it.

    Showing the threshold beside the triggering value makes the bullet
    self-explaining — "why did this fire?" is answerable without reading the source.
    """
    item = for_finding(finding.kind)
    parts = [f"**{item.label}** — {item.what}", f"_How to read it:_ {item.how_to_read}"]

    if finding.threshold is not None and finding.evidence:
        measured = next(iter(finding.evidence.values()))
        if finding.kind in {"beta", "avg_correlation", "high_corr_pairs"}:
            shown, limit = f"{measured:.2f}", f"{finding.threshold:.2f}"
        else:
            shown, limit = f"{measured:.1%}", f"{finding.threshold:.1%}"
        parts.append(
            f"_Why it fired:_ measured **{shown}**, against a "
            f"{finding.severity} threshold of {limit}."
        )

    if item.caveat:
        parts.append(f"_Caveat:_ {item.caveat}")
    return "\n\n".join(parts)


SEVERITY_KEYS = {"HIGH": "severity.high", "MEDIUM": "severity.medium", "LOW": "severity.low"}
SEVERITY_ICONS = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "⚪"}


def severity_help(severity: str) -> str:
    return tooltip(SEVERITY_KEYS[severity])
