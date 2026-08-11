"""Local persistence: the last portfolio, ticker corrections, and CSV export.

Everything lives under `data/`, which is git-ignored. Nothing here reaches the network
and nothing is written outside the project directory.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.ingest.schema import KNOWN_COLUMNS
from src.risk.valuation import ValuedPortfolio

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORTFOLIO_FILE = "portfolio.csv"
TICKER_FIXES_FILE = "ticker_fixes.json"

EXPORT_COLUMNS = [
    "ticker",
    "name",
    "quantity",
    "cost_basis",
    "base_currency",
    "asset_class",
    "theme",
    "isin",
]
assert set(EXPORT_COLUMNS) <= set(KNOWN_COLUMNS)


def write_portfolio_csv(portfolio: ValuedPortfolio, path: Path) -> Path:
    """Write a portfolio back out in the app's own input format.

    The output must load back through `load_portfolio` unchanged — that round trip is
    asserted in the integration tests.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for holding in portfolio.holdings:
            writer.writerow(
                {
                    "ticker": holding.ticker,
                    "name": holding.name or "",
                    "quantity": f"{holding.quantity:.10g}",
                    "cost_basis": "" if holding.cost_basis is None else f"{holding.cost_basis:.2f}",
                    "base_currency": portfolio.base_currency,
                    "asset_class": holding.asset_class or "",
                    "theme": holding.theme or "",
                    "isin": holding.isin or "",
                }
            )
    return path


def save_portfolio(portfolio: ValuedPortfolio, *, data_dir: Path | None = None) -> Path:
    """Persist the current portfolio so the next session reloads it."""
    directory = data_dir or DATA_DIR
    return write_portfolio_csv(portfolio, directory / PORTFOLIO_FILE)


def saved_portfolio_path(*, data_dir: Path | None = None) -> Path | None:
    path = (data_dir or DATA_DIR) / PORTFOLIO_FILE
    return path if path.exists() else None


def load_ticker_fixes(*, data_dir: Path | None = None) -> dict[str, str]:
    """User-supplied corrections: original ticker or ISIN -> confirmed symbol."""
    path = (data_dir or DATA_DIR) / TICKER_FIXES_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_ticker_fixes(fixes: dict[str, str], *, data_dir: Path | None = None) -> Path:
    directory = data_dir or DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / TICKER_FIXES_FILE
    path.write_text(json.dumps(fixes, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def portfolio_csv(portfolio: ValuedPortfolio) -> str:
    """Serialise a portfolio to the app's own CSV format, in memory.

    Used by the download button. Round-trips through `load_portfolio` unchanged.
    """
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for holding in portfolio.holdings:
        writer.writerow(
            {
                "ticker": holding.ticker,
                "name": holding.name or "",
                "quantity": f"{holding.quantity:.10g}",
                "cost_basis": "" if holding.cost_basis is None else f"{holding.cost_basis:.2f}",
                "base_currency": portfolio.base_currency,
                "asset_class": holding.asset_class or "",
                "theme": holding.theme or "",
                "isin": holding.isin or "",
            }
        )
    return buffer.getvalue()
