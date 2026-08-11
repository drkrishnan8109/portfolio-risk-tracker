"""Tests I1-I21 — the CSV contract.

The app's entire input surface. One bad row must never fail a file, and a blank ticker is
an *unresolved holding*, not a rejection: a portfolio can legitimately contain something
with a genuine quantity and cost basis but no market symbol.
"""

from __future__ import annotations

import pytest

from src.ingest.loader import FileValidationError, load_portfolio


def write(tmp_path, text: str, name: str = "p.csv", encoding: str = "utf-8"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


HEADER = "ticker,quantity,name,cost_basis,base_currency,asset_class,theme,isin\n"


# --- I1-I8: parsing ----------------------------------------------------------------


def test_i1_minimal_file(tmp_path):
    result = load_portfolio(write(tmp_path, "ticker,quantity\nAAPL,10\n"))
    assert len(result.holdings) == 1
    holding = result.holdings[0]
    assert holding.ticker == "AAPL"
    assert holding.quantity == 10.0
    assert holding.cost_basis is None
    assert result.rejections == []


def test_i2_full_file(tmp_path):
    path = write(tmp_path, HEADER + "AAPL,10,Apple Inc.,1500.50,USD,EQUITY,Big Tech,US0378331005\n")
    holding = load_portfolio(path).holdings[0]
    assert holding.ticker == "AAPL"
    assert holding.name == "Apple Inc."
    assert holding.quantity == 10.0
    assert holding.cost_basis == 1500.50
    assert holding.asset_class == "EQUITY"
    assert holding.theme == "Big Tech"
    assert holding.isin == "US0378331005"


def test_i3_column_order_irrelevant(tmp_path):
    a = load_portfolio(write(tmp_path, "ticker,quantity,cost_basis\nAAPL,10,1500\n", "a.csv"))
    b = load_portfolio(write(tmp_path, "cost_basis,quantity,ticker\n1500,10,AAPL\n", "b.csv"))
    assert a.holdings == b.holdings


def test_i4_unknown_column_ignored(tmp_path):
    path = write(tmp_path, "ticker,quantity,broker_note\nAAPL,10,some note\n")
    result = load_portfolio(path)
    assert len(result.holdings) == 1
    assert result.rejections == []


def test_i5_utf8_bom_stripped(tmp_path):
    path = write(tmp_path, "ticker,quantity\nAAPL,10\n", encoding="utf-8-sig")
    result = load_portfolio(path)
    assert len(result.holdings) == 1
    assert result.holdings[0].ticker == "AAPL"


def test_i6_quoted_field_with_comma(tmp_path):
    path = write(tmp_path, 'ticker,quantity,name\nMETA,5,"Meta Platforms, Inc."\n')
    assert load_portfolio(path).holdings[0].name == "Meta Platforms, Inc."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [('"1,250"', 1250.0), ('"12,500.50"', 12500.50), ("1250", 1250.0), ("1250.5", 1250.5)],
)
def test_i7_thousands_separators(tmp_path, raw, expected):
    path = write(tmp_path, f"ticker,quantity\nAAPL,{raw}\n")
    assert load_portfolio(path).holdings[0].quantity == expected


def test_i8_blank_line_skipped(tmp_path):
    path = write(tmp_path, "ticker,quantity\nAAPL,10\n\nMSFT,5\n")
    result = load_portfolio(path)
    assert len(result.holdings) == 2
    assert result.rejections == []


# --- I9-I12, I17: validation -------------------------------------------------------


def test_i9_missing_required_header(tmp_path):
    with pytest.raises(FileValidationError) as exc:
        load_portfolio(write(tmp_path, "symbol,quantity\nAAPL,10\n"))
    assert "ticker" in str(exc.value)


@pytest.mark.parametrize("quantity", ["0", "0.0", "-15", "abc", ""])
def test_i10_i11_i12_invalid_quantity_rejected(tmp_path, quantity):
    path = write(tmp_path, f"ticker,quantity\nAAPL,10\nMSFT,{quantity}\n")
    result = load_portfolio(path)
    assert [h.ticker for h in result.holdings] == ["AAPL"]
    assert len(result.rejections) == 1
    assert result.rejections[0].ticker == "MSFT"
    assert result.rejections[0].line == 3


def test_i12_reason_names_the_bad_value(tmp_path):
    path = write(tmp_path, "ticker,quantity\nMSFT,abc\n")
    assert "abc" in load_portfolio(path).rejections[0].reason


def test_i17_mixed_base_currency_fails_the_file(tmp_path):
    path = write(tmp_path, "ticker,quantity,base_currency\nAAPL,10,USD\nRHM.DE,5,EUR\n")
    with pytest.raises(FileValidationError) as exc:
        load_portfolio(path)
    message = str(exc.value)
    assert "USD" in message and "EUR" in message


def test_uniform_base_currency_sets_reporting_currency(tmp_path):
    path = write(tmp_path, "ticker,quantity,base_currency\nAAPL,10,EUR\nRHM.DE,5,EUR\n")
    assert load_portfolio(path).base_currency == "EUR"


def test_absent_base_currency_uses_default(tmp_path):
    path = write(tmp_path, "ticker,quantity\nAAPL,10\n")
    assert load_portfolio(path, default_base_currency="GBP").base_currency == "GBP"


# --- I13-I14: blanks ---------------------------------------------------------------


def test_i13_blank_ticker_is_kept_unresolved(tmp_path):
    path = write(tmp_path, "ticker,quantity,name,cost_basis\n,7,Untraded Holding,1234.00\n")
    result = load_portfolio(path)
    assert result.rejections == []
    holding = result.holdings[0]
    assert holding.ticker == ""
    assert holding.resolved is False
    assert holding.quantity == 7.0
    assert holding.cost_basis == 1234.00


def test_i14_blank_cost_basis_is_none_not_zero(tmp_path):
    path = write(tmp_path, "ticker,quantity,cost_basis\nAAPL,10,\n")
    holding = load_portfolio(path).holdings[0]
    assert holding.cost_basis is None
    assert holding.cost_basis != 0.0


def test_explicit_zero_cost_basis_is_zero(tmp_path):
    path = write(tmp_path, "ticker,quantity,cost_basis\nAAPL,10,0\n")
    assert load_portfolio(path).holdings[0].cost_basis == 0.0


# --- I15-I16, I21: duplicates ------------------------------------------------------


def test_i15_duplicate_tickers_aggregate(tmp_path):
    path = write(tmp_path, "ticker,quantity,cost_basis\nAAPL,40,7920\nAAPL,25,4100\n")
    result = load_portfolio(path)
    assert len(result.holdings) == 1
    holding = result.holdings[0]
    assert holding.quantity == 65.0
    assert holding.cost_basis == 12020.0
    assert holding.source_lines == (2, 3)


def test_i15_merge_is_reported(tmp_path):
    path = write(tmp_path, "ticker,quantity,cost_basis\nAAPL,40,7920\nAAPL,25,4100\n")
    merges = load_portfolio(path).merges
    assert len(merges) == 1
    assert merges[0].ticker == "AAPL"
    assert merges[0].lines == (2, 3)


def test_i16_duplicate_with_one_blank_basis_yields_none(tmp_path):
    path = write(tmp_path, "ticker,quantity,cost_basis\nAAPL,40,7920\nAAPL,25,\n")
    holding = load_portfolio(path).holdings[0]
    assert holding.quantity == 65.0
    assert holding.cost_basis is None  # a partial sum would misstate P&L


def test_i21_blank_tickers_do_not_merge(tmp_path):
    path = write(tmp_path, "ticker,quantity,name\n,4,Untraded A\n,10,Untraded B\n")
    result = load_portfolio(path)
    assert len(result.holdings) == 2
    assert result.merges == []


# --- I18-I20: file-level behaviour -------------------------------------------------


def test_i18_bad_row_does_not_fail_good_rows(tmp_path):
    path = write(tmp_path, "ticker,quantity\nAAPL,10\nMSFT,-5\nGOOG,7\n")
    result = load_portfolio(path)
    assert [h.ticker for h in result.holdings] == ["AAPL", "GOOG"]
    assert result.rejections[0].line == 3


def test_i19_malformed_fixture(portfolios_dir):
    result = load_portfolio(portfolios_dir / "malformed.csv")
    # AAPL (merged), the blank-ticker row, PEP, JNJ
    assert len(result.holdings) == 4
    # zero quantity, negative quantity, non-numeric quantity
    assert len(result.rejections) == 3
    assert {r.ticker for r in result.rejections} == {"MSFT", "GOOG", "META"}

    by_ticker = {h.ticker: h for h in result.holdings}
    assert by_ticker["AAPL"].quantity == 65.0
    assert by_ticker["AAPL"].cost_basis == 12020.0
    assert by_ticker["PEP"].quantity == 1250.0
    assert by_ticker["PEP"].cost_basis == 12500.0
    assert by_ticker["JNJ"].cost_basis is None
    assert by_ticker[""].resolved is False


def test_i20_header_only_file(tmp_path):
    result = load_portfolio(write(tmp_path, "ticker,quantity\n"))
    assert result.holdings == []
    assert result.rejections == []


def test_real_fixture_loads(real_portfolio):
    result = load_portfolio(real_portfolio)
    assert len(result.holdings) == 19
    assert result.base_currency == "EUR"
    assert sum(1 for h in result.holdings if not h.resolved) == 1
    assert result.rejections == []


def test_balanced_and_speculative_fixtures_load(portfolios_dir):
    balanced = load_portfolio(portfolios_dir / "balanced_index.csv")
    assert len(balanced.holdings) == 11
    assert balanced.base_currency == "EUR"

    speculative = load_portfolio(portfolios_dir / "concentrated_speculative.csv")
    assert len(speculative.holdings) == 11
    assert speculative.base_currency == "USD"
    blanks = [h for h in speculative.holdings if h.cost_basis is None]
    assert {h.ticker for h in blanks} == {"RIOT", "SMCI"}
