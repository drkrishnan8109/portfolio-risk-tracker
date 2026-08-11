"""The ⓘ layer: one explanation per displayed number.

A metric a reader cannot interpret is worse than no metric — it invites a confident
wrong conclusion. So every number the app renders is keyed to an entry here, and tests
assert the two sets match in both directions.

`how_to_read` carries the weight. "Standard deviation of daily returns scaled by root
252" teaches nothing; "above ~20% means a 20% swing in a year is ordinary, not alarming"
does. Entries describe; they never advise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    label: str
    what: str
    how_to_read: str
    formula: str | None = None
    caveat: str | None = None

    def tooltip(self) -> str:
        """Markdown for a Streamlit `help=` argument."""
        parts = [f"**{self.label}** — {self.what}", f"_How to read it:_ {self.how_to_read}"]
        if self.formula:
            parts.append(f"_Formula:_ `{self.formula}`")
        if self.caveat:
            parts.append(f"_Caveat:_ {self.caveat}")
        return "\n\n".join(parts)


E = GlossaryEntry

GLOSSARY: dict[str, GlossaryEntry] = {
    # --- KPIs ---------------------------------------------------------------------
    "kpi.total_value": E(
        label="Total value",
        what="Market value of every holding we could price, in your reporting currency.",
        how_to_read=(
            "What the portfolio is worth today. The timestamp beside it tells you how "
            "stale that is. Holdings without a price are excluded from this figure."
        ),
    ),
    "kpi.cost_basis": E(
        label="Cost basis",
        what="Total paid for the positions you still hold.",
        how_to_read=(
            "Not 'money ever put in' — closed positions are gone from it. This is what "
            "is still at work. Blank if any holding is missing a cost basis."
        ),
    ),
    "kpi.unrealized_pnl": E(
        label="Unrealised P&L",
        what="Market value minus cost basis, across open positions.",
        how_to_read=(
            "The gain or loss you would realise by closing everything at today's prices, "
            "before tax and fees."
        ),
    ),
    "kpi.position_count": E(
        label="Positions",
        what="Number of holdings with a quantity greater than zero.",
        how_to_read=(
            "A rough diversification proxy only. Nineteen positions with eight in one "
            "theme is less diversified than eight spread across five."
        ),
    ),
    "kpi.currency_exposure": E(
        label="Largest currency",
        what="Share of value priced in the single most common currency.",
        how_to_read=(
            "How much of a result reported in your currency actually depends on another "
            "one moving."
        ),
    ),
    # --- distribution views -------------------------------------------------------
    "view.by_holding": E(
        label="By holding",
        what="Each position's share of total value.",
        how_to_read="The top bar is your largest single point of failure.",
    ),
    "view.by_asset_class": E(
        label="By asset class",
        what="Value split across equities, funds, commodities and crypto products.",
        how_to_read="Shows whether your risk is one type of thing wearing several names.",
        caveat=(
            "Where the file does not declare an asset class it is guessed from market "
            "data, which cannot tell a physical-commodity ETC from an ETF."
        ),
    ),
    "view.by_sector": E(
        label="By sector",
        what="Value split across the sector of each holding.",
        how_to_read=(
            "Understates true exposure when you hold thematic funds, because a fund "
            "spans sectors and lands in its own bucket. Read it beside the theme view."
        ),
    ),
    "view.by_theme": E(
        label="By theme",
        what="Value split across the theme tags in your file.",
        how_to_read=(
            "Catches what sector cannot: a thematic fund and the individual stocks it "
            "already holds are one bet, not two."
        ),
        caveat="Only as good as your tags — which is why they are yours to edit.",
    ),
    "view.by_currency": E(
        label="By currency",
        what="Value split by the currency each holding is priced in.",
        how_to_read=(
            "Everything is reported in one currency, but a foreign holding carries "
            "exchange-rate risk on top of company risk."
        ),
    ),
    # --- concentration -------------------------------------------------------------
    "concentration.position_weight": E(
        label="Position weight",
        what="One holding as a percentage of the portfolio.",
        how_to_read=(
            "Above roughly 15% a position materially drives your returns; above 25% it "
            "dominates them."
        ),
    ),
    "concentration.top5_share": E(
        label="Top-5 share",
        what="Combined weight of your five largest positions.",
        how_to_read=(
            "Above roughly 55% the remaining holdings are close to decorative — they "
            "cannot move the total much."
        ),
    ),
    "concentration.hhi": E(
        label="Concentration index (HHI)",
        what="Sum of squared position weights — one number for how concentrated you are.",
        how_to_read=(
            "Runs from 1/N when everything is equally sized to 1.0 when it is all in one "
            "position. Lower is more spread out."
        ),
        formula="HHI = sum(weight^2)",
        caveat=(
            "Counts positions, ignores correlation. Ten holdings that move together "
            "score as diversified — read it beside average correlation and theme."
        ),
    ),
    "concentration.effective_positions": E(
        label="Effective positions",
        what="How many equally-sized holdings the portfolio behaves like.",
        how_to_read=(
            "Usually far below your actual count. Nineteen holdings behaving like nine "
            "means the small ones barely register."
        ),
        formula="1 / HHI",
    ),
    "concentration.sector": E(
        label="Sector concentration",
        what="Largest single sector's share of value.",
        how_to_read=(
            "Sectors fall together in downturns, so 40% in one behaves more like a "
            "single large position than several small ones."
        ),
        caveat="Understated when thematic funds sit in their own bucket.",
    ),
    "concentration.theme": E(
        label="Theme concentration",
        what="Largest theme tag's share of value.",
        how_to_read=(
            "The figure that survives the fund blind spot — direct holdings and thematic "
            "funds counted as the single bet they are."
        ),
    ),
    "concentration.asset_class": E(
        label="Asset-class concentration",
        what="Largest asset class's share of value.",
        how_to_read="Whether one asset type having a bad year is your bad year.",
    ),
    # --- volatility and downside ----------------------------------------------------
    "risk.volatility_position": E(
        label="Volatility (position)",
        what="How much one holding's daily price moves, expressed per year.",
        how_to_read=(
            "Around 15% is typical for a broad index; 40% or more is a high-variance "
            "single name or a crypto product."
        ),
    ),
    "risk.volatility_portfolio": E(
        label="Volatility (portfolio)",
        what="Annualised volatility of the blended portfolio return.",
        how_to_read=(
            "Normally lower than the average of its holdings — that gap is "
            "diversification working. If it is barely lower, your holdings move together."
        ),
        caveat="Backward-looking. A calm past year does not promise a calm next one.",
    ),
    "risk.beta": E(
        label="Beta",
        what=(
            "Sensitivity to the benchmark. 1.0 moves with the market, 1.5 moves half "
            "again as hard."
        ),
        how_to_read=(
            "Above roughly 1.2 you carry amplified market risk in both directions; below "
            "1.0 you are damped relative to it."
        ),
        caveat=(
            "Captures only market-linked risk. Gold and crypto can show a low beta and "
            "still be very risky."
        ),
    ),
    "risk.max_drawdown": E(
        label="Maximum drawdown",
        what="Largest peak-to-trough fall over the window measured.",
        how_to_read=(
            "The worst stretch this portfolio actually lived through. A useful gut "
            "check: could you have held on through that without flinching?"
        ),
        caveat="History, not a worst case. The next fall can exceed it.",
    ),
    "risk.var_95": E(
        label="Value at Risk (95%)",
        what="The one-day loss threshold breached on the worst 5% of days.",
        how_to_read=(
            "On the worst day in twenty you would expect to lose at least this much. A "
            "threshold, not a ceiling."
        ),
        caveat="Says nothing about how bad the other 5% of days get — that is CVaR.",
    ),
    "risk.cvar_95": E(
        label="Conditional VaR (95%)",
        what="Average loss on the days that breach the VaR threshold.",
        how_to_read=(
            "Your typical bad-day loss once a bad day actually arrives. Always worse "
            "than VaR, and the more honest of the two."
        ),
    ),
    "risk.downside_deviation": E(
        label="Downside deviation",
        what="Volatility computed from losing days only.",
        how_to_read=(
            "Separates painful movement from pleasant movement — a sharp rise does not "
            "inflate it the way plain volatility does."
        ),
    ),
    # --- diversification -------------------------------------------------------------
    "diversification.correlation_matrix": E(
        label="Correlation matrix",
        what="How closely each pair of holdings moves together, from -1 to +1.",
        how_to_read=(
            "+1 is lockstep, 0 unrelated, -1 opposite. Blocks of high values are "
            "clusters that will fall together."
        ),
    ),
    "diversification.avg_correlation": E(
        label="Average correlation",
        what="Mean correlation across every pair of holdings.",
        how_to_read=(
            "Above roughly 0.6, holdings that look separate are largely one bet. Below "
            "0.3, diversification is genuinely reducing your risk."
        ),
        caveat=(
            "Correlations rise in a crisis, so the diversification measured in calm "
            "markets partly evaporates exactly when it is needed."
        ),
    ),
    "diversification.high_corr_pairs": E(
        label="Near-identical pairs",
        what="Count of holding pairs correlated above 0.8.",
        how_to_read=(
            "Each pair is effectively one position held twice. A high count means your "
            "position count overstates real diversification."
        ),
    ),
    # --- currency ---------------------------------------------------------------------
    "fx.exposure_by_currency": E(
        label="Currency exposure",
        what="Portfolio value grouped by each holding's pricing currency.",
        how_to_read=(
            "A rate move changes your total with no company doing anything at all."
        ),
    ),
    "fx.rate": E(
        label="Exchange rate used",
        what="The rate every conversion on this page was made at, and when it was taken.",
        how_to_read=(
            "A different rate shifts every converted figure here. Worth checking when "
            "values disagree with your broker's."
        ),
    ),
    # --- trend --------------------------------------------------------------------------
    "trend.dma_50": E(
        label="vs 50-day average",
        what="Price relative to its average over the last 50 trading days.",
        how_to_read="Above is short-term upward momentum; below suggests recent weakness.",
        caveat="A description of the recent past, not a forecast.",
    ),
    "trend.dma_200": E(
        label="vs 200-day average",
        what="Price relative to its average over the last 200 trading days.",
        how_to_read="The conventional dividing line between a long-term uptrend and downtrend.",
        caveat="Whipsaws in sideways markets. Context, not a signal.",
    ),
    "trend.high_52w_distance": E(
        label="From 52-week high",
        what="How far below its one-year high a holding trades.",
        how_to_read=(
            "Minus 10% is routine noise; minus 30% or more usually means something "
            "changed for that holding."
        ),
    ),
    "trend.below_200dma_weighted": E(
        label="Value below 200-day average",
        what="Share of portfolio value trading under its own 200-day average.",
        how_to_read="Above roughly 40%, weakness is broad rather than isolated to one name.",
    ),
    # --- data quality ---------------------------------------------------------------------
    "data.insufficient_history": E(
        label="Insufficient history",
        what="Holdings with fewer than 60 trading days of prices.",
        how_to_read=(
            "Excluded from volatility, beta, drawdown, VaR and correlation, because "
            "those need history to mean anything. Still counted in value and weight."
        ),
    ),
    "data.unresolved_ticker": E(
        label="Unresolved holding",
        what="A holding with no usable market symbol.",
        how_to_read=(
            "Shown at cost and kept visible, but excluded from priced metrics and from "
            "the percentage weights, so concentration is not distorted by a blank."
        ),
    ),
    "data.rejected_rows": E(
        label="Rejected rows",
        what="Rows in your file that failed validation, with the reason for each.",
        how_to_read=(
            "Listed so you can confirm nothing real was dropped. A rejected row has no "
            "effect on any number on this page."
        ),
    ),
    "data.merged_duplicates": E(
        label="Merged rows",
        what="The same ticker appearing on several lines, combined into one holding.",
        how_to_read=(
            "Quantities and cost bases were summed. If two lines were meant to be "
            "different instruments, give them different tickers."
        ),
    ),
    "data.price_staleness": E(
        label="Price age",
        what="When the prices behind this view were last fetched.",
        how_to_read="Older than one trading day means these are not today's values.",
    ),
    "data.asset_class_inferred": E(
        label="Asset class guessed",
        what="Asset class taken from market data because your file did not declare one.",
        how_to_read=(
            "Market data cannot distinguish a physical-commodity ETC from an ordinary "
            "fund. Add an asset_class column to make it exact."
        ),
    ),
    # --- severity --------------------------------------------------------------------------
    "severity.high": E(
        label="High",
        what="A number past the point where it materially shapes portfolio outcomes.",
        how_to_read="Worth a deliberate decision, which may well be to leave it alone.",
    ),
    "severity.medium": E(
        label="Medium",
        what="Elevated and worth knowing about.",
        how_to_read="Often perfectly reasonable when it is intentional.",
    ),
    "severity.low": E(
        label="Low",
        what="Informational context.",
        how_to_read="Noted so the readout is complete, not because anything is wrong.",
    ),
}

#: Finding kind (from `src.risk.rules`) -> glossary key.
FINDING_KIND_KEYS: dict[str, str] = {
    "position_weight": "concentration.position_weight",
    "top5_share": "concentration.top5_share",
    "sector_concentration": "concentration.sector",
    "theme_concentration": "concentration.theme",
    "currency_exposure": "fx.exposure_by_currency",
    "portfolio_volatility": "risk.volatility_portfolio",
    "max_drawdown": "risk.max_drawdown",
    "avg_correlation": "diversification.avg_correlation",
    "beta": "risk.beta",
    "crypto_allocation": "concentration.asset_class",
    "below_200dma": "trend.below_200dma_weighted",
    "high_corr_pairs": "diversification.high_corr_pairs",
}

#: Every key the UI is allowed to render. Kept here so tests can check both directions.
DISPLAYED_KEYS: frozenset[str] = frozenset(GLOSSARY)


class UnknownGlossaryKey(KeyError):
    """A number was rendered with no explanation attached."""


def entry(key: str) -> GlossaryEntry:
    """Look up an entry, failing loudly rather than rendering a bare number."""
    try:
        return GLOSSARY[key]
    except KeyError as exc:
        raise UnknownGlossaryKey(
            f"No glossary entry for {key!r}. Every displayed number needs one."
        ) from exc


def tooltip(key: str) -> str:
    return entry(key).tooltip()


def for_finding(kind: str) -> GlossaryEntry:
    """Explanation for a finding, looked up by its kind."""
    return entry(FINDING_KIND_KEYS[kind])
