"""Currency conversion.

All rates are held against a single pivot (EUR) and cross rates are derived, so adding a
currency means adding one pair rather than N.

`GBp` is the trap this module exists to contain: Yahoo quotes several LSE-listed
instruments in *pence*, one hundredth of a pound. Treating `GBp` as `GBP` overstates
those positions by 100x. Currency codes are therefore **case-sensitive** here — unlike
the base currency in `src.ingest`, which is upper-cased on the way in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

PIVOT = "EUR"

#: Sub-unit quotes: code -> (major currency, sub-units per major).
SUBUNITS: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 100.0),
    "ILA": ("ILS", 100.0),
    "ZAc": ("ZAR", 100.0),
}


class UnknownCurrencyError(KeyError):
    """A currency code has no known rate. Never silently treated as 1.0."""

    def __init__(self, code: str) -> None:
        label = repr(code) if code else "an empty currency code"
        super().__init__(f"No exchange rate for {label}")
        self.code = code


def _pivot_rate(code: str, rates: dict[str, float]) -> float:
    """Units of `code` per one unit of the pivot currency."""
    if code in SUBUNITS:
        major, per_major = SUBUNITS[code]
        return _pivot_rate(major, rates) * per_major
    try:
        return rates[code]
    except (KeyError, TypeError) as exc:
        raise UnknownCurrencyError(code) from exc


def factor(native: str, base: str, rates: dict[str, float]) -> float:
    """Multiplier converting an amount in `native` into `base`.

    Args:
        native: Currency the amount is quoted in, e.g. `USD` or `GBp`.
        base: Reporting currency.
        rates: Units per one pivot (EUR) unit. Must contain both currencies, unless
            they are equal.

    Raises:
        UnknownCurrencyError: Either code is absent. A missing rate must never
            degrade to 1.0 — that would report a foreign quote as a base-currency value.
    """
    if native == base:
        return 1.0
    return _pivot_rate(base, rates) / _pivot_rate(native, rates)


def _leg(code: str, fx: Mapping[str, pd.Series], index: pd.Index) -> pd.Series:
    """Units of `code` per one pivot unit, aligned to `index` and forward-filled."""
    if code == PIVOT:
        return pd.Series(1.0, index=index)

    scale = 1.0
    if code in SUBUNITS:
        code, scale = SUBUNITS[code]
    if code not in fx:
        raise UnknownCurrencyError(code)

    series = fx[code]
    aligned = series.reindex(index.union(series.index)).ffill().reindex(index)
    return aligned * scale


def convert_series(
    prices: pd.Series,
    *,
    native: str,
    base: str,
    fx: Mapping[str, pd.Series] | None,
) -> pd.Series:
    """Convert a price series into `base`, aligning rates to the price dates.

    Both legs route through the pivot, so any base currency works — a USD-reporting
    portfolio holding a EUR-quoted ETF converts correctly without a EURUSD-specific path.

    Missing rate days are carried **forward** only. A price predating every known rate
    yields NaN rather than borrowing a later rate, which would be lookahead bias.

    Args:
        prices: Price series indexed by date, quoted in `native`.
        native: Quote currency of `prices`, e.g. `USD` or `GBp`.
        base: Reporting currency.
        fx: Currency code -> series of units per one pivot (EUR) unit. Only the legs
            actually needed are looked up. Ignored when `native == base`.
    """
    if native == base:
        return prices
    if fx is None:
        raise UnknownCurrencyError(native)

    native_leg = _leg(native, fx, prices.index)
    base_leg = _leg(base, fx, prices.index)
    converted = prices / native_leg * base_leg
    return pd.Series(converted.to_numpy(), index=prices.index, name=prices.name)


@dataclass(frozen=True)
class FxRates:
    """A point-in-time rate table, carrying the timestamp it was captured at.

    Every converted figure on screen depends on these rates, so the app states which
    ones it used and when they were taken.
    """

    base: str
    rates: dict[str, float] = field(default_factory=dict)
    as_of: pd.Timestamp | None = None

    @classmethod
    def from_series(
        cls,
        fx_series: dict[str, pd.Series],
        *,
        base: str,
        as_of: pd.Timestamp | None = None,
    ) -> FxRates:
        """Build a table from EUR-pivoted rate series, using each one's last observation."""
        rates: dict[str, float] = {PIVOT: 1.0}
        stamps: list[pd.Timestamp] = []
        for code, series in fx_series.items():
            clean = series.dropna()
            if clean.empty:
                continue
            rates[code] = float(clean.iloc[-1])
            stamps.append(clean.index[-1])
        return cls(base=base, rates=rates, as_of=as_of or (max(stamps) if stamps else None))

    def factor(self, native: str) -> float:
        return factor(native, self.base, self.rates)

    def to_base(self, amount: float, *, native: str) -> float:
        """Convert a single amount into the reporting currency."""
        return amount * self.factor(native)

    def describe(self, native: str) -> str:
        """One line naming the rate used and when it was taken, for the UI tooltip."""
        rate = self.factor(native)
        stamp = self.as_of.date().isoformat() if self.as_of is not None else "unknown date"
        return f"1 {native} = {rate:.4f} {self.base} (rate as of {stamp})"
