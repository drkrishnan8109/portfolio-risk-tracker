"""Field-level parsing for the portfolio CSV.

Blank and zero are different everywhere in this module: a blank `cost_basis` means
"unknown" and must not become 0.0, which would silently report a 100% gain.
"""

from __future__ import annotations


class NumberFormatError(ValueError):
    """A field that should hold a number does not."""


def parse_number(raw: str | None) -> float | None:
    """Parse a numeric field, tolerating thousands separators.

    Returns None for a blank field — the caller decides whether that is allowed.

    Raises:
        NumberFormatError: the value is present but not a number. The message quotes
            the offending value so the rejection reason can name it.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError as exc:
        raise NumberFormatError(f"{raw.strip()!r} is not a number") from exc


def clean(raw: str | None) -> str | None:
    """Strip a text field; empty becomes None so optional columns stay absent."""
    if raw is None:
        return None
    text = raw.strip()
    return text or None


def normalise_ticker(raw: str | None) -> str:
    """Uppercase and strip a symbol. Blank stays blank — that is an unresolved holding."""
    return (raw or "").strip().upper()


def normalise_currency(raw: str | None) -> str | None:
    """Uppercase a currency code.

    Note this is for the *base* currency declared in the file. Pricing currencies from
    the market data provider are handled in `src.market.fx`, which is deliberately
    case-sensitive because `GBp` (pence) and `GBP` (pounds) are different units.
    """
    text = clean(raw)
    return text.upper() if text else None


def is_blank_row(row: dict[str, str | None]) -> bool:
    """True when every field is empty — a spacer line, not a data row."""
    return all(not (value or "").strip() for value in row.values())
