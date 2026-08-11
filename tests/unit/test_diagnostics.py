"""Tests D1-D14 — deciding what to warn the user about, and how loudly.

The dialog itself is layout, but *what counts as a problem* is logic and belongs under
test. Two levels matter:

* **Blocking** — the file cannot be read at all. Nothing renders; the user must fix it.
* **Non-blocking** — the analysis is valid but something was dropped, merged or could not
  be priced. Silence here is the dangerous case: a portfolio quietly missing three rows
  still produces confident-looking percentages.
"""

from __future__ import annotations

import io

import pytest

from src.ingest.diagnostics import Diagnostics, describe_failure, diagnose
from src.ingest.loader import FileValidationError, load_portfolio
from src.ingest.schema import Holding, LoadResult, Merge, Rejection
from src.risk.valuation import ValuedHolding, ValuedPortfolio


def result(holdings=(), rejections=(), merges=(), currency="USD") -> LoadResult:
    return LoadResult(
        holdings=list(holdings),
        rejections=list(rejections),
        merges=list(merges),
        base_currency=currency,
    )


def portfolio(holdings=()) -> ValuedPortfolio:
    return ValuedPortfolio(holdings=list(holdings), base_currency="USD")


# --- D1: the quiet case ----------------------------------------------------------------


def test_d1_clean_file_has_no_issues():
    diag = diagnose(result(holdings=[Holding("AAPL", 10.0)]))
    assert diag.has_issues is False
    assert diag.issues == []
    assert diag.blocking is False


def test_d1_clean_diagnostics_is_falsy():
    assert not diagnose(result(holdings=[Holding("AAPL", 10.0)]))


# --- D2-D6: each kind of problem --------------------------------------------------------


def test_d2_rejected_rows_are_an_error():
    diag = diagnose(result(rejections=[Rejection(3, "MSFT", "quantity must be positive, got 0")]))
    issue = diag.by_kind("rejected_rows")
    assert issue.severity == "error"
    assert issue.rows[0]["line"] == 3
    assert "quantity" in issue.rows[0]["reason"]


def test_d2_rejection_summary_counts_rows():
    diag = diagnose(
        result(rejections=[Rejection(3, "A", "bad"), Rejection(4, "B", "bad")])
    )
    assert "2 row" in diag.by_kind("rejected_rows").summary


def test_d3_merged_duplicates_are_a_warning():
    diag = diagnose(result(merges=[Merge("AAPL", (2, 3), 65.0, 12020.0)]))
    issue = diag.by_kind("merged_duplicates")
    assert issue.severity == "warning"
    assert issue.rows[0]["ticker"] == "AAPL"
    assert issue.rows[0]["lines"] == "2, 3"


def test_d4_unpriced_holdings_are_a_warning():
    diag = diagnose(
        result(),
        portfolio(
            [ValuedHolding("", 4.0, name="SK Hynix GDR", unavailable_reason="no ticker supplied")]
        ),
    )
    issue = diag.by_kind("unpriced")
    assert issue.severity == "warning"
    assert "excluded from the percentages" in issue.detail
    assert issue.rows[0]["reason"] == "no ticker supplied"


def test_d5_insufficient_history_is_informational():
    diag = diagnose(
        result(),
        portfolio([ValuedHolding("SKHY", 5.0, value=100.0, insufficient_history=True, points=22)]),
    )
    issue = diag.by_kind("insufficient_history")
    assert issue.severity == "info"
    assert issue.rows[0]["trading days"] == 22


def test_d6_inferred_asset_class_is_informational():
    diag = diagnose(
        result(),
        portfolio([ValuedHolding("IGLN.L", 1.0, value=100.0, asset_class_inferred=True)]),
    )
    assert diagnose_kinds(diag) == {"inferred_asset_class"}


def diagnose_kinds(diag: Diagnostics) -> set[str]:
    return {issue.kind for issue in diag.issues}


def test_priced_holding_with_history_raises_nothing():
    diag = diagnose(result(), portfolio([ValuedHolding("AAPL", 1.0, value=100.0)]))
    assert diag.has_issues is False


# --- D7-D8: ordering and shape ------------------------------------------------------------


def test_d7_errors_sort_before_warnings_before_info():
    diag = diagnose(
        result(
            rejections=[Rejection(3, "A", "bad")],
            merges=[Merge("AAPL", (2, 3), 1.0, 1.0)],
        ),
        portfolio([ValuedHolding("SKHY", 1.0, value=1.0, insufficient_history=True, points=22)]),
    )
    assert [i.severity for i in diag.issues] == ["error", "warning", "info"]


def test_d8_headline_names_the_worst_severity():
    clean = diagnose(result(holdings=[Holding("AAPL", 1.0)]))
    assert clean.headline is None

    warned = diagnose(result(merges=[Merge("AAPL", (2, 3), 1.0, 1.0)]))
    assert "check" in warned.headline.lower() or "issue" in warned.headline.lower()

    errored = diagnose(result(rejections=[Rejection(3, "A", "bad")]))
    assert errored.worst_severity == "error"


def test_d8_worst_severity_of_a_clean_file_is_none():
    assert diagnose(result(holdings=[Holding("AAPL", 1.0)])).worst_severity is None


# --- D9-D12: blocking failures ---------------------------------------------------------------


def test_d9_missing_column_error_is_structured():
    with pytest.raises(FileValidationError) as exc:
        load_portfolio(io.StringIO("symbol,quantity\nAAPL,10\n"))

    failure = describe_failure(exc.value)
    assert "ticker" in failure.title or "ticker" in failure.detail
    assert failure.fix, "a blocking error must tell the user how to fix it"
    assert "symbol" in failure.detail, "name the columns actually found"


def test_d10_mixed_currency_error_names_both_currencies():
    with pytest.raises(FileValidationError) as exc:
        load_portfolio(
            io.StringIO("ticker,quantity,base_currency\nAAPL,10,USD\nRHM.DE,5,EUR\n")
        )

    failure = describe_failure(exc.value)
    assert "USD" in failure.detail and "EUR" in failure.detail
    assert failure.fix


def test_d11_failure_description_is_never_empty():
    failure = describe_failure(FileValidationError("something went wrong"))
    assert failure.title
    assert failure.detail
    assert failure.fix


def test_d12_blocking_diagnostics_reports_itself():
    diag = Diagnostics.blocking_failure(
        describe_failure(FileValidationError("Missing required column(s): ticker. Found: symbol"))
    )
    assert diag.blocking is True
    assert diag.has_issues is True
    assert diag.worst_severity == "error"


# --- D13-D14: against the real fixtures ---------------------------------------------------------


def test_d13_malformed_fixture_produces_the_expected_issues(portfolios_dir):
    loaded = load_portfolio(portfolios_dir / "malformed.csv")
    diag = diagnose(loaded)

    assert diag.blocking is False
    assert diag.has_issues is True
    assert diagnose_kinds(diag) == {"rejected_rows", "merged_duplicates"}

    rejected = diag.by_kind("rejected_rows")
    assert len(rejected.rows) == 3
    assert {r["ticker"] for r in rejected.rows} == {"MSFT", "GOOG", "META"}
    assert all(r["line"] for r in rejected.rows), "every rejection needs its source line"

    merged = diag.by_kind("merged_duplicates")
    assert merged.rows[0]["ticker"] == "AAPL"


def test_d14_real_fixture_reports_only_soft_issues(real_portfolio, repo, fx_series):
    from src.market.fx import FxRates
    from src.risk.valuation import value_portfolio

    loaded = load_portfolio(real_portfolio)
    valued = value_portfolio(
        loaded.holdings,
        repo=repo,
        base_currency=loaded.base_currency,
        fx_series=fx_series,
        fx_rates=FxRates.from_series(fx_series, base=loaded.base_currency),
    )
    diag = diagnose(loaded, valued)

    assert diag.blocking is False
    assert diag.worst_severity == "warning", "no rows were rejected, so nothing is an error"
    assert diagnose_kinds(diag) >= {"unpriced", "insufficient_history"}
    assert diag.by_kind("unpriced").rows[0]["name"] == "SK Hynix GDR"
    assert {r["ticker"] for r in diag.by_kind("insufficient_history").rows} == {"SKHY", "SPCX"}


def test_balanced_fixture_is_completely_clean(portfolios_dir, repo, fx_series):
    from src.market.fx import FxRates
    from src.risk.valuation import value_portfolio

    loaded = load_portfolio(portfolios_dir / "balanced_index.csv")
    valued = value_portfolio(
        loaded.holdings,
        repo=repo,
        base_currency=loaded.base_currency,
        fx_series=fx_series,
        fx_rates=FxRates.from_series(fx_series, base=loaded.base_currency),
    )
    diag = diagnose(loaded, valued)
    assert diag.has_issues is False, f"unexpected issues: {diagnose_kinds(diag)}"
