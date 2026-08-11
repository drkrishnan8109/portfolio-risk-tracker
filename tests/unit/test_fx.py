"""Tests F1-F8 — currency conversion.

The headline case is `GBp`. Yahoo quotes several LSE instruments in *pence*, not pounds
(SGLN.L in balanced_index.csv is one). Treating that as GBP overstates the position by
100x, which would show a ~9% gold sleeve as ~900% of the portfolio.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.market.fx import FxRates, UnknownCurrencyError, convert_series, factor

# 1 EUR buys this many units of each currency.
RATES = {"EUR": 1.0, "USD": 1.15, "CHF": 0.94, "GBP": 0.85}


def test_f1_same_currency_is_identity_without_lookup():
    # Passing an empty rate table proves no lookup happens on the identity path.
    assert factor("USD", "USD", {}) == 1.0
    assert factor("EUR", "EUR", {}) == 1.0


def test_f2_usd_to_eur():
    assert factor("USD", "EUR", RATES) == pytest.approx(1 / 1.15)
    assert 115.0 * factor("USD", "EUR", RATES) == pytest.approx(100.0)


def test_f2_eur_to_usd_is_the_inverse():
    assert factor("EUR", "USD", RATES) == pytest.approx(1.15)


def test_f2_cross_rate_via_pivot():
    # USD -> CHF should not need a USDCHF pair; it routes through EUR.
    assert factor("USD", "CHF", RATES) == pytest.approx(0.94 / 1.15)


def test_f3_gbp_pence_is_one_hundredth_of_a_pound():
    pounds = factor("GBP", "EUR", RATES)
    pence = factor("GBp", "EUR", RATES)
    assert pence == pytest.approx(pounds / 100)


def test_f3_sgln_gold_sleeve_is_not_inflated():
    """The regression this test exists for: SGLN.L quotes at ~6282 GBp, not 6282 GBP."""
    quote_in_pence = 6282.20
    value_eur = 160 * quote_in_pence * factor("GBp", "EUR", RATES)
    assert 10_000 < value_eur < 14_000  # ~EUR 11.8k, not ~EUR 1.18m


def test_f4_gbp_and_gbp_pence_differ_by_exactly_100x():
    assert factor("GBP", "EUR", RATES) / factor("GBp", "EUR", RATES) == pytest.approx(100.0)


def test_f4_pence_case_is_significant():
    # 'GBP' and 'GBp' differ only by case and mean different units, so the lookup
    # must not upper-case currency codes.
    assert factor("GBP", "EUR", RATES) != factor("GBp", "EUR", RATES)


@pytest.mark.parametrize("code", ["JPY", "XXX", "", "usd"])
def test_f5_unknown_currency_raises_naming_the_code(code):
    with pytest.raises(UnknownCurrencyError) as exc:
        factor(code, "EUR", RATES)
    assert code in str(exc.value) or "empty" in str(exc.value).lower()


def test_f5_never_silently_returns_one():
    """A silent 1.0 would value a foreign holding at its raw quote. Must raise instead."""
    with pytest.raises(UnknownCurrencyError):
        factor("JPY", "EUR", RATES)


# --- F6-F7: time-aligned series conversion ------------------------------------------


def _dates(n, start="2026-01-01"):
    return pd.date_range(start, periods=n, freq="D")


def test_f6_series_converted_pointwise():
    idx = _dates(3)
    prices = pd.Series([100.0, 110.0, 120.0], index=idx)
    fx = pd.Series([1.0, 2.0, 4.0], index=idx)  # 1 EUR = n USD
    out = convert_series(prices, native="USD", base="EUR", fx={"USD": fx})
    assert list(out) == pytest.approx([100.0, 55.0, 30.0])


def test_f6_missing_fx_day_forward_fills():
    idx = _dates(4)
    prices = pd.Series([100.0] * 4, index=idx)
    fx = pd.Series([2.0, np.nan, np.nan, 4.0], index=idx)
    out = convert_series(prices, native="USD", base="EUR", fx={"USD": fx})
    # days 2 and 3 carry day 1's rate forward
    assert list(out) == pytest.approx([50.0, 50.0, 50.0, 25.0])


def test_f6_fx_reindexed_onto_price_dates():
    prices = pd.Series([100.0, 100.0, 100.0], index=_dates(3, "2026-03-02"))
    fx = pd.Series([2.0], index=pd.DatetimeIndex(["2026-03-01"]))  # stale but valid
    out = convert_series(prices, native="USD", base="EUR", fx={"USD": fx})
    assert list(out) == pytest.approx([50.0, 50.0, 50.0])


def test_f7_forward_fill_never_looks_ahead():
    """A price predating every known rate must be NaN, not back-filled from the future."""
    prices = pd.Series([100.0, 100.0], index=_dates(2, "2026-01-01"))
    fx = pd.Series([2.0], index=pd.DatetimeIndex(["2026-01-02"]))
    out = convert_series(prices, native="USD", base="EUR", fx={"USD": fx})
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(50.0)


def test_f7_same_currency_series_untouched():
    prices = pd.Series([1.0, 2.0], index=_dates(2))
    out = convert_series(prices, native="EUR", base="EUR", fx=None)
    pd.testing.assert_series_equal(out, prices)


def test_series_pence_conversion():
    idx = _dates(2)
    prices = pd.Series([6000.0, 6000.0], index=idx)  # GBp
    fx = pd.Series([0.85, 0.85], index=idx)  # 1 EUR = 0.85 GBP
    out = convert_series(prices, native="GBp", base="EUR", fx={"GBP": fx})
    assert list(out) == pytest.approx([60.0 / 0.85] * 2)


# --- F8: provenance -----------------------------------------------------------------


def test_f8_rates_carry_an_as_of_timestamp():
    stamp = pd.Timestamp("2026-08-11")
    table = FxRates(base="EUR", rates=RATES, as_of=stamp)
    assert table.as_of == stamp
    assert table.to_base(115.0, native="USD") == pytest.approx(100.0)


def test_f8_describe_names_rate_and_timestamp():
    table = FxRates(base="EUR", rates=RATES, as_of=pd.Timestamp("2026-08-11"))
    text = table.describe("USD")
    assert "USD" in text and "2026-08-11" in text


def test_f8_from_series_uses_last_observation(fx_series):
    table = FxRates.from_series(fx_series, base="EUR")
    assert table.rates["USD"] == pytest.approx(float(fx_series["USD"].iloc[-1]))
    assert table.rates["EUR"] == 1.0
    assert table.as_of == fx_series["USD"].index[-1]


def test_from_series_supports_a_non_eur_base(fx_series):
    """A USD-reporting user still gets correct factors from EUR-pivoted inputs."""
    table = FxRates.from_series(fx_series, base="USD")
    eur_per_usd = 1 / float(fx_series["USD"].iloc[-1])
    assert table.to_base(1.0, native="EUR") == pytest.approx(float(fx_series["USD"].iloc[-1]))
    assert table.to_base(1.0, native="USD") == 1.0
    assert eur_per_usd > 0


def test_convert_series_supports_a_non_eur_base():
    """A USD-reporting portfolio holding a EUR-quoted ETF (e.g. XAIX.DE)."""
    idx = _dates(2)
    prices = pd.Series([200.0, 200.0], index=idx)  # EUR
    fx = {"USD": pd.Series([1.15, 1.15], index=idx)}
    out = convert_series(prices, native="EUR", base="USD", fx=fx)
    assert list(out) == pytest.approx([230.0, 230.0])


def test_convert_series_cross_currency_without_a_direct_pair():
    """GBp -> USD routes through the pivot; no GBPUSD series required."""
    idx = _dates(1)
    prices = pd.Series([6000.0], index=idx)  # GBp = GBP 60
    fx = {"GBP": pd.Series([0.85], index=idx), "USD": pd.Series([1.15], index=idx)}
    out = convert_series(prices, native="GBp", base="USD", fx=fx)
    assert out.iloc[0] == pytest.approx(60.0 / 0.85 * 1.15)


def test_convert_series_missing_leg_raises():
    idx = _dates(1)
    prices = pd.Series([100.0], index=idx)
    with pytest.raises(UnknownCurrencyError):
        convert_series(prices, native="JPY", base="EUR", fx={"USD": pd.Series([1.15], index=idx)})
