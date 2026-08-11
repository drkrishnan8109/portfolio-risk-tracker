"""What to tell the user went wrong with their file.

Two levels:

* **Blocking** — the file cannot be read at all. Nothing renders until it is fixed, so the
  message has to say what is wrong *and* how to fix it.
* **Non-blocking** — the analysis is valid, but rows were rejected, merged, or could not be
  priced. Silence here is the dangerous case: a portfolio quietly missing three rows still
  produces confident-looking percentages, and the reader has no way to know.

This module decides *what counts as a problem and how loudly to say it*. Rendering it as a
dialog is `app.py`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]

_ORDER: dict[Severity, int] = {"error": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Failure:
    """A blocking problem, phrased for someone who did not write the parser."""

    title: str
    detail: str
    fix: str


@dataclass(frozen=True)
class Issue:
    """One category of non-blocking problem, with the offending rows attached."""

    kind: str
    severity: Severity
    summary: str
    detail: str
    rows: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Diagnostics:
    """Everything worth telling the user about their file."""

    issues: list[Issue] = field(default_factory=list)
    failure: Failure | None = None

    @classmethod
    def blocking_failure(cls, failure: Failure) -> Diagnostics:
        return cls(issues=[], failure=failure)

    @property
    def blocking(self) -> bool:
        return self.failure is not None

    @property
    def has_issues(self) -> bool:
        return bool(self.issues) or self.blocking

    def __bool__(self) -> bool:
        return self.has_issues

    @property
    def worst_severity(self) -> Severity | None:
        if self.blocking:
            return "error"
        if not self.issues:
            return None
        return min((i.severity for i in self.issues), key=lambda s: _ORDER[s])

    @property
    def headline(self) -> str | None:
        """One line for the dialog title, or None when there is nothing to say."""
        worst = self.worst_severity
        if worst is None:
            return None
        if self.blocking:
            return self.failure.title
        counts = sum(len(i.rows) or 1 for i in self.issues)
        if worst == "error":
            return f"Some rows could not be used ({counts} to check)"
        return f"Worth a check before you read the numbers ({counts} item(s))"

    def by_kind(self, kind: str) -> Issue | None:
        return next((i for i in self.issues if i.kind == kind), None)


def describe_failure(error: Exception) -> Failure:
    """Turn a loader exception into something a person can act on.

    The loader's messages are already specific; this adds a title and a concrete fix so
    the dialog never shows a bare exception string.
    """
    message = str(error)

    if "Missing required column" in message:
        return Failure(
            title="That file is missing a required column",
            detail=message,
            fix=(
                "Every portfolio file needs a `ticker` column and a `quantity` column. "
                "Download the template from the sidebar to see the expected header, then "
                "rename your columns to match. Column order does not matter, and any extra "
                "columns are ignored."
            ),
        )

    if "base_currency" in message:
        return Failure(
            title="That file mixes reporting currencies",
            detail=message,
            fix=(
                "Every row must share one `base_currency`, because the whole report is "
                "produced in a single currency. Convert the cost basis of the odd rows "
                "yourself, or drop the `base_currency` column entirely and pick a currency "
                "in the sidebar instead."
            ),
        )

    return Failure(
        title="That file could not be read as a portfolio",
        detail=message or "The file could not be parsed.",
        fix=(
            "Check it is a comma-separated CSV with a header row. The template in the "
            "sidebar is a working example."
        ),
    )


def diagnose(loaded, portfolio=None) -> Diagnostics:
    """Collect every non-blocking problem worth surfacing.

    Args:
        loaded: A `LoadResult` from `src.ingest.loader`.
        portfolio: An optional `ValuedPortfolio`; pricing problems are only knowable
            once the market data has been fetched.
    """
    issues: list[Issue] = []

    if loaded.rejections:
        issues.append(
            Issue(
                kind="rejected_rows",
                severity="error",
                summary=f"{len(loaded.rejections)} row(s) could not be read and were skipped",
                detail=(
                    "These rows are not part of any number on the page. Fix them and "
                    "re-upload if they matter."
                ),
                rows=[
                    {"line": r.line, "ticker": r.ticker or "(blank)", "reason": r.reason}
                    for r in loaded.rejections
                ],
            )
        )

    if loaded.merges:
        issues.append(
            Issue(
                kind="merged_duplicates",
                severity="warning",
                summary=f"{len(loaded.merges)} ticker(s) appeared on more than one line",
                detail=(
                    "Quantities and cost bases were added together. If those lines were "
                    "meant to be different instruments, give them different tickers."
                ),
                rows=[
                    {
                        "ticker": m.ticker,
                        "lines": ", ".join(str(line) for line in m.lines),
                        "quantity": m.quantity,
                        "cost_basis": m.cost_basis,
                    }
                    for m in loaded.merges
                ],
            )
        )

    if portfolio is not None:
        issues.extend(_pricing_issues(portfolio))

    return Diagnostics(issues=sorted(issues, key=lambda i: _ORDER[i.severity]))


def _pricing_issues(portfolio) -> list[Issue]:
    issues: list[Issue] = []

    unpriced = list(portfolio.unpriced)
    if unpriced:
        issues.append(
            Issue(
                kind="unpriced",
                severity="warning",
                summary=f"{len(unpriced)} holding(s) could not be priced",
                detail=(
                    "These stay visible with their cost basis, but are excluded from the "
                    "percentages so concentration is not distorted by a missing value."
                ),
                rows=[
                    {
                        "ticker": h.ticker or "(none)",
                        "name": h.name,
                        "quantity": h.quantity,
                        "cost basis": h.cost_basis,
                        "reason": h.unavailable_reason,
                    }
                    for h in unpriced
                ],
            )
        )

    short = [h for h in portfolio.priced if h.insufficient_history]
    if short:
        issues.append(
            Issue(
                kind="insufficient_history",
                severity="info",
                summary=f"{len(short)} holding(s) have too little price history",
                detail=(
                    "Fewer than 60 trading days, so volatility, beta, drawdown, VaR and "
                    "correlation are left blank for them. They still count towards value "
                    "and weight."
                ),
                rows=[{"ticker": h.ticker, "trading days": h.points} for h in short],
            )
        )

    inferred = [h for h in portfolio.priced if h.asset_class_inferred]
    if inferred:
        issues.append(
            Issue(
                kind="inferred_asset_class",
                severity="info",
                summary=f"{len(inferred)} holding(s) had their asset class guessed",
                detail=(
                    "Your file did not declare one, so it was taken from market data - "
                    "which cannot tell a physical-commodity ETC from an ordinary fund. "
                    "Add an `asset_class` column to make it exact."
                ),
                rows=[
                    {"ticker": h.ticker, "guessed": h.asset_class or "unknown"} for h in inferred
                ],
            )
        )

    return issues
