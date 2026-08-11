"""Load a portfolio CSV into validated holdings.

Two principles drive the error handling:

* One bad row never fails a file. Rejections are collected with their source line number
  and surfaced in the UI, so the user can see exactly what was dropped and why.
* A blank ticker is an unresolved *holding*, not a rejection. Only a file-level problem
  (missing required column, conflicting base currencies) raises.
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from collections.abc import Iterable
from io import StringIO
from pathlib import Path
from typing import IO

from src.ingest.parsing import (
    NumberFormatError,
    clean,
    is_blank_row,
    normalise_currency,
    normalise_ticker,
    parse_number,
)
from src.ingest.schema import (
    DEFAULT_BASE_CURRENCY,
    REQUIRED_COLUMNS,
    Holding,
    LoadResult,
    Merge,
    Rejection,
)


class FileValidationError(Exception):
    """The file cannot be interpreted as a portfolio at all."""


def _open_text(source: str | Path | IO[str]) -> tuple[Iterable[str], object | None]:
    """Return line iterable plus a handle to close, accepting a path, text, or buffer."""
    if isinstance(source, str | Path):
        path = Path(source)
        handle = path.open(encoding="utf-8-sig", newline="")
        return handle, handle
    text = source.read()
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    elif text.startswith("﻿"):
        text = text[1:]
    return StringIO(text), None


def load_portfolio(
    source: str | Path | IO[str],
    *,
    default_base_currency: str = DEFAULT_BASE_CURRENCY,
) -> LoadResult:
    """Parse a portfolio CSV.

    Args:
        source: Path, or any text/binary buffer (a Streamlit upload works directly).
        default_base_currency: Used when the file declares no `base_currency`.

    Raises:
        FileValidationError: A required column is missing, or the file declares more
            than one base currency.
    """
    lines, to_close = _open_text(source)
    try:
        reader = csv.DictReader(lines)
        fieldnames = [(name or "").strip() for name in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
        if missing:
            raise FileValidationError(
                f"Missing required column(s): {', '.join(missing)}. "
                f"Found: {', '.join(fieldnames) or '(no header)'}"
            )
        rows = [(reader.line_num, {(k or "").strip(): v for k, v in row.items()}) for row in reader]
    finally:
        if to_close is not None:
            to_close.close()

    parsed: list[tuple[int, Holding]] = []
    rejections: list[Rejection] = []
    currencies: OrderedDict[str, None] = OrderedDict()

    for line, row in rows:
        if is_blank_row(row):
            continue

        ticker = normalise_ticker(row.get("ticker"))
        currency = normalise_currency(row.get("base_currency"))
        if currency:
            currencies.setdefault(currency, None)

        try:
            quantity = parse_number(row.get("quantity"))
        except NumberFormatError as exc:
            rejections.append(Rejection(line, ticker or None, f"quantity: {exc}"))
            continue

        if quantity is None:
            rejections.append(Rejection(line, ticker or None, "quantity is required"))
            continue
        if quantity <= 0:
            rejections.append(
                Rejection(line, ticker or None, f"quantity must be positive, got {quantity:g}")
            )
            continue

        try:
            cost_basis = parse_number(row.get("cost_basis"))
        except NumberFormatError as exc:
            rejections.append(Rejection(line, ticker or None, f"cost_basis: {exc}"))
            continue

        asset_class = clean(row.get("asset_class"))
        parsed.append(
            (
                line,
                Holding(
                    ticker=ticker,
                    quantity=quantity,
                    name=clean(row.get("name")),
                    cost_basis=cost_basis,
                    asset_class=asset_class.upper() if asset_class else None,
                    theme=clean(row.get("theme")),
                    isin=clean(row.get("isin")),
                    source_lines=(line,),
                ),
            )
        )

    if len(currencies) > 1:
        raise FileValidationError(
            "base_currency must be the same on every row; found "
            + ", ".join(currencies)
            + ". Convert the file to a single reporting currency first."
        )
    base_currency = next(iter(currencies), None) or default_base_currency.upper()

    holdings, merges = _combine_duplicates(parsed)
    return LoadResult(
        holdings=holdings,
        rejections=rejections,
        merges=merges,
        base_currency=base_currency,
    )


def _combine_duplicates(parsed: list[tuple[int, Holding]]) -> tuple[list[Holding], list[Merge]]:
    """Aggregate rows sharing a ticker.

    Unresolved rows (blank ticker) are never combined: two untradeable lines are two
    different instruments, not one listed twice.

    A merged `cost_basis` is None if *any* contributor is None — a partial sum would
    understate the basis and overstate the gain.
    """
    grouped: OrderedDict[str, list[Holding]] = OrderedDict()
    singles: list[Holding] = []

    for _, holding in parsed:
        if not holding.ticker:
            singles.append(holding)
        else:
            grouped.setdefault(holding.ticker, []).append(holding)

    holdings: list[Holding] = []
    merges: list[Merge] = []

    for ticker, group in grouped.items():
        if len(group) == 1:
            holdings.append(group[0])
            continue

        lines = tuple(sorted(line for h in group for line in h.source_lines))
        quantity = sum(h.quantity for h in group)
        bases = [h.cost_basis for h in group]
        cost_basis = None if any(b is None for b in bases) else sum(bases)
        first = group[0]
        holdings.append(
            Holding(
                ticker=ticker,
                quantity=quantity,
                name=next((h.name for h in group if h.name), None),
                cost_basis=cost_basis,
                asset_class=next((h.asset_class for h in group if h.asset_class), None),
                theme=next((h.theme for h in group if h.theme), None),
                isin=next((h.isin for h in group if h.isin), first.isin),
                source_lines=lines,
            )
        )
        merges.append(Merge(ticker=ticker, lines=lines, quantity=quantity, cost_basis=cost_basis))

    holdings.extend(singles)
    return holdings, merges
