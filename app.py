"""Portfolio Risk Tracker — Streamlit entry point.

Layout only. Every number on this page is computed in `src/`; nothing here does
arithmetic beyond formatting, which keeps the whole analysis testable without a browser.
What counts as a file problem is decided in `src/ingest/diagnostics.py`; this module only
renders it.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.content.glossary import GLOSSARY
from src.ingest.diagnostics import Diagnostics, Failure, describe_failure, diagnose
from src.ingest.loader import FileValidationError, load_portfolio
from src.market.fx import FxRates
from src.market.live import (
    DEFAULT_BENCHMARK,
    benchmark_closes,
    build_repository,
    currencies_for,
    fx_series_for,
)
from src.narrative.client import build_client
from src.narrative.explain import explain
from src.risk.engine import analyse
from src.risk.valuation import value_portfolio
from src.store import portfolio_csv, save_portfolio, saved_portfolio_path
from src.viz import charts
from src.viz.info import SEVERITY_ICONS, finding_help, help_for, severity_help

load_dotenv()

st.set_page_config(page_title="Portfolio Risk Tracker", page_icon="📉", layout="wide")

TEMPLATE = (
    "ticker,name,quantity,cost_basis,base_currency,asset_class,theme,isin\n"
    "AAPL,Apple Inc.,50,9000.00,USD,EQUITY,Big Tech,US0378331005\n"
)

VIEWS = {
    "By holding": ("view.by_holding", "weights"),
    "By asset class": ("view.by_asset_class", "by_asset_class"),
    "By theme": ("view.by_theme", "by_theme"),
    "By currency": ("view.by_currency", "by_currency"),
    "By sector": ("view.by_sector", "by_sector"),
}


@st.cache_resource
def _repo():
    return build_repository()


@st.cache_data(show_spinner=False)
def _analyse(csv_bytes: bytes, base_default: str, benchmark: str):
    """Full pipeline. Cached on the file contents so reruns are instant."""
    loaded = load_portfolio(io.StringIO(csv_bytes.decode("utf-8-sig")),
                            default_base_currency=base_default)
    repo = _repo()
    tickers = [h.ticker for h in loaded.holdings if h.ticker]
    currencies = currencies_for(repo, tickers)
    fx = fx_series_for(repo, set(currencies.values()) | {loaded.base_currency})
    portfolio = value_portfolio(
        loaded.holdings,
        repo=repo,
        base_currency=loaded.base_currency,
        fx_series=fx,
        fx_rates=FxRates.from_series(fx, base=loaded.base_currency),
    )
    bench = benchmark_closes(
        repo, symbol=benchmark, base_currency=loaded.base_currency, fx_series=fx
    )
    return loaded, analyse(portfolio, benchmark_closes=bench)


def money(value: float | None, currency: str) -> str:
    return "—" if value is None else f"{value:,.0f} {currency}"


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


ISSUE_ICONS = {"error": "🔴", "warning": "🟠", "info": "🔵"}


def render_issues(diag: Diagnostics) -> None:
    """Each issue: what happened, what it means, and the offending rows."""
    for issue in diag.issues:
        st.markdown(f"{ISSUE_ICONS[issue.severity]} **{issue.summary}**")
        st.caption(issue.detail)
        if issue.rows:
            st.dataframe(pd.DataFrame(issue.rows), width="stretch", hide_index=True)
        st.write("")


@st.dialog("Problem with your file", width="large")
def failure_dialog(failure: Failure) -> None:
    """Shown when the file cannot be read at all — nothing else will render."""
    st.error(failure.title)
    st.markdown("**What happened**")
    st.markdown(failure.detail)
    st.markdown("**How to fix it**")
    st.markdown(failure.fix)
    st.download_button(
        "Download a working template", TEMPLATE, "portfolio_template.csv", "text/csv"
    )


@st.dialog("File report", width="large")
def issues_dialog(diag: Diagnostics) -> None:
    """Shown when the file loaded but something was dropped, merged or unpriceable."""
    (st.error if diag.worst_severity == "error" else st.warning)(diag.headline)
    st.caption(
        "The analysis behind this dialog is still valid — it is computed from the rows "
        "that loaded cleanly. This is here so you know what was left out."
    )
    st.divider()
    render_issues(diag)


# ---------------------------------------------------------------- sidebar

st.sidebar.title("📉 Portfolio Risk Tracker")
st.sidebar.caption("Upload a CSV of what you currently hold.")

uploaded = st.sidebar.file_uploader("Portfolio CSV", type="csv")
base_default = st.sidebar.selectbox(
    "Base currency (used only if your file has no `base_currency` column)",
    ["USD", "EUR", "GBP", "CHF"],
    index=0,
)
benchmark = st.sidebar.text_input("Benchmark for beta", DEFAULT_BENCHMARK)
st.sidebar.download_button("Download CSV template", TEMPLATE, "portfolio_template.csv", "text/csv")

with st.sidebar.expander("Required columns"):
    st.markdown(
        "`ticker` and `quantity` are required. `name`, `cost_basis`, `base_currency`, "
        "`asset_class`, `theme` and `isin` are optional.\n\n"
        "A blank `ticker` keeps the holding visible but leaves it out of the "
        "percentages — useful for something untradeable."
    )

client_status = build_client()
st.sidebar.caption(f"**Narrative:** {client_status.mode_label}")
if client_status.reason:
    st.sidebar.caption(client_status.reason)

source_bytes: bytes | None = None
if uploaded is not None:
    source_bytes = uploaded.getvalue()
    st.session_state["has_upload"] = True
elif (previous := saved_portfolio_path()) is not None:
    source_bytes = Path(previous).read_bytes()
    st.sidebar.info("Showing the last portfolio you analysed.")

# ---------------------------------------------------------------- body

st.title("Portfolio risk")

if source_bytes is None:
    st.info("Upload a portfolio CSV in the sidebar to begin.")
    st.markdown(
        "Need a starting point? Download the template, or try one of the example "
        "portfolios in `tests/fixtures/portfolios/`."
    )
    st.stop()

digest = hashlib.sha256(source_bytes).hexdigest()

try:
    with st.spinner("Fetching prices…"):
        loaded, analysis = _analyse(
            source_bytes, base_default, benchmark.strip() or DEFAULT_BENCHMARK
        )
except FileValidationError as exc:
    failure = describe_failure(exc)
    # Pop the dialog once per bad file, and leave the message on the page too so it
    # survives the modal being dismissed.
    reopen = st.session_state.get("reported_failure") != digest
    st.session_state["reported_failure"] = digest
    st.error(f"**{failure.title}**")
    st.markdown(failure.detail)
    st.info(failure.fix)
    if st.button("Show details") or reopen:
        failure_dialog(failure)
    st.stop()

currency = analysis.base_currency
if uploaded is not None:
    save_portfolio(analysis.portfolio)

diagnostics = diagnose(loaded, analysis.portfolio)

# Open the report automatically the first time a file is seen, and leave a control to
# reopen it. Only one dialog may run per script pass, so both paths share a call site.
open_report = False
if diagnostics.has_issues:
    if st.session_state.get("reported_issues") != digest:
        st.session_state["reported_issues"] = digest
        open_report = True

    message, action = st.columns([6, 1])
    with message:
        (st.error if diagnostics.worst_severity == "error" else st.warning)(diagnostics.headline)
    if action.button("View report", width="stretch"):
        open_report = True

if open_report:
    issues_dialog(diagnostics)

# --- headline ------------------------------------------------------------

kpis = st.columns(5)
kpis[0].metric(
    "Total value", money(analysis.total_value, currency), help=help_for("kpi.total_value")
)
kpis[1].metric(
    "Cost basis", money(analysis.total_cost_basis, currency), help=help_for("kpi.cost_basis")
)
kpis[2].metric(
    "Unrealised P&L",
    money(analysis.unrealised_pnl, currency),
    delta=None if analysis.unrealised_pnl is None or not analysis.total_cost_basis
    else f"{analysis.unrealised_pnl / analysis.total_cost_basis:.1%}",
    help=help_for("kpi.unrealized_pnl"),
)
kpis[3].metric("Positions", len(analysis.portfolio.holdings), help=help_for("kpi.position_count"))
largest_currency = analysis.inputs.largest_currency
kpis[4].metric(
    "Largest currency",
    f"{largest_currency[0]} {largest_currency[1]:.0%}" if largest_currency else "—",
    help=help_for("kpi.currency_exposure"),
)

if analysis.portfolio.fx and analysis.portfolio.fx.as_of is not None:
    stamp, info = st.columns([12, 1])
    stamp.caption(
        f"Prices as of {analysis.as_of:%Y-%m-%d} · "
        f"FX as of {analysis.portfolio.fx.as_of:%Y-%m-%d}"
    )
    with info.popover("ⓘ", help="Exchange rates used"):
        st.markdown(help_for("fx.rate"))

st.divider()

# --- section 1: distribution ---------------------------------------------

left, right = st.columns([3, 2], gap="large")

with left:
    header, info = st.columns([6, 1])
    header.subheader("What you hold")
    choice = st.radio("Breakdown", list(VIEWS), horizontal=True, label_visibility="collapsed")
    glossary_key, attribute = VIEWS[choice]
    with info.popover("ⓘ", help="What this breakdown shows"):
        st.markdown(help_for(glossary_key))

    shares: pd.Series = getattr(analysis, attribute)
    if shares.empty:
        st.info(
            "No data for this breakdown. "
            + ("Add a `theme` column to your CSV to enable it." if attribute == "by_theme"
               else "Add a `sector` column to your CSV to enable it."
               if attribute == "by_sector" else "")
        )
    else:
        values = pd.Series(
            {
                (h.ticker or h.name or "unnamed"): h.value
                for h in analysis.portfolio.holdings
                if h.priced
            }
        ) if attribute == "weights" else None
        st.plotly_chart(
            charts.share_bar(
                shares,
                title=f"share of portfolio ({currency})",
                base_currency=currency,
                values=values,
            ),
            width="stretch",
        )
        with st.expander("Table view"):
            st.dataframe(
                pd.DataFrame({"share": shares}).style.format({"share": "{:.2%}"}),
                width="stretch",
            )

with right:
    st.subheader("Portfolio statistics")
    stats = [
        (
            "Volatility (annualised)",
            pct(analysis.portfolio_volatility),
            "risk.volatility_portfolio",
        ),
        ("Beta", f"{analysis.portfolio_beta:.2f}" if analysis.portfolio_beta else "—", "risk.beta"),
        ("Max drawdown", pct(analysis.portfolio_max_drawdown), "risk.max_drawdown"),
        ("VaR (95%, 1 day)", pct(analysis.portfolio_var_95), "risk.var_95"),
        ("CVaR (95%, 1 day)", pct(analysis.portfolio_cvar_95), "risk.cvar_95"),
        (
            "Concentration (HHI)",
            f"{analysis.hhi:.3f}" if analysis.hhi else "—",
            "concentration.hhi",
        ),
        (
            "Effective positions",
            f"{analysis.effective_positions:.1f}" if analysis.effective_positions else "—",
            "concentration.effective_positions",
        ),
        ("Top-5 share", pct(analysis.top5_share), "concentration.top5_share"),
        (
            "Average correlation",
            f"{analysis.avg_correlation:.2f}" if analysis.avg_correlation is not None else "—",
            "diversification.avg_correlation",
        ),
    ]
    for label, value, key in stats:
        row = st.columns([3, 2, 1])
        row[0].markdown(f"**{label}**")
        row[1].markdown(value)
        with row[2].popover("ⓘ", help=label):
            st.markdown(help_for(key))

st.divider()

# --- section 2: risks -----------------------------------------------------

st.subheader("What could hurt you")
narrative = explain(analysis.findings, client=client_status.client)
if narrative.warning:
    st.caption(f"⚠️ {narrative.warning}")

if not analysis.findings:
    st.success(narrative.bullets[0].text)
else:
    for bullet, finding in zip(narrative.bullets, analysis.findings, strict=False):
        row = st.columns([12, 1])
        row[0].markdown(f"{SEVERITY_ICONS[bullet.severity]} {bullet.text}")
        with row[1].popover("ⓘ", help=f"{bullet.severity} finding"):
            st.markdown(finding_help(finding))
            st.markdown("---")
            st.markdown(severity_help(finding.severity))

st.caption(
    "This is an analysis of exposures in a portfolio you supplied. It is not financial "
    "advice, and it makes no recommendation to buy or sell anything."
)

# --- file report ----------------------------------------------------------

with st.expander("File report", expanded=False):
    if diagnostics.has_issues:
        render_issues(diagnostics)
    else:
        st.success("Every row parsed and priced cleanly.")
    st.download_button(
        "Download the parsed portfolio",
        portfolio_csv(analysis.portfolio),
        "portfolio.csv",
        "text/csv",
        help="Re-uploads cleanly: this is the same format the app reads.",
    )

with st.expander("Glossary"):
    st.caption(f"{len(GLOSSARY)} metrics, each with an explanation.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "metric": e.label,
                    "what it measures": e.what,
                    "how to read it": e.how_to_read,
                }
                for e in GLOSSARY.values()
            ]
        ),
        width="stretch",
        hide_index=True,
    )
