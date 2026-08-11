# Spec: Portfolio Risk Tracker

**Status:** v3 — **implemented**. Deltas found during the build are recorded below.
**Date:** 2026-08-11

---

## What changed from v2

| v2 | v3 |
|---|---|
| Two upload modes: transactions **or** portfolio | **One** input: a current-portfolio CSV |
| "Prepare portfolio CSV" tab converted transactions → holdings | **Removed from the app.** Users bring their own portfolio CSV. |
| Broker-specific ingest (Scalable Capital dialect, ISIN-keyed, German decimals) | **Broker-agnostic**, ticker-keyed |
| Tests written alongside implementation | **TDD is the governing method** — every module's tests exist and fail before its code is written |
| Fixtures to be invented later | **Three real fixtures already built and profiled**, plus a validation fixture |

The transaction-conversion logic is not deleted, it is **demoted**: it survives as
`tools/build_portfolio_from_scalable.py`, a one-off repo utility whose only job is regenerating
one test fixture. It is not imported by the app, not on any code path, and not maintained as a
feature. Nothing in `src/` may import from `tools/`.

**Why this is the right call:** custody migrations, unrecorded splits, corporate-action row pairs
and per-broker sign conventions are an unbounded surface — each broker export has its own traps
(this one had three). Owning that surface makes the app a broker-integration project. Owning a
single well-specified CSV makes it a risk-analysis project, which is what it is for.

---

## Objective

A Streamlit app that takes a current-portfolio CSV and returns a two-part risk readout: **what the
portfolio is made of**, and **what could hurt it**.

**User:** any individual investor who can produce a CSV of what they hold — from a broker export,
a spreadsheet, or by hand.

**Success:** upload a CSV → allocation chart and a ranked list of specific, numeric risk bullets,
in under 30 seconds. No configuration beyond picking a base currency.

### User stories

| # | Story | Acceptance |
|---|---|---|
| U1 | Upload a portfolio CSV | Parses; every rejected row is listed with a reason and its source line number. Nothing silently dropped. |
| U2 | Get a template | A download button emits a valid empty CSV with the documented header, and a link to a filled example. |
| U3 | See portfolio distribution | Allocation chart, switchable by holding / asset class / sector / theme / currency. |
| U4 | See risks in bullets | Ranked bullets, each with severity, the triggering number, and an ⓘ. |
| U5 | Fix a bad ticker without leaving the app | Unresolved tickers appear in an editable table; each edit is validated against live history before it is accepted. |
| U6 | Come back tomorrow | Last portfolio, ticker corrections and cached prices reload from disk. |

### Out of scope

Transaction ingest, lot accounting, corporate actions, realized-gain or tax reporting, options,
shorts, backtesting, rebalancing advice, alerting, multi-portfolio comparison, auth, hosting.

---

## Input contract — the portfolio CSV

The app's entire input surface. Comma-delimited, UTF-8 (BOM tolerated), header row required,
column order irrelevant, unknown columns preserved and ignored.

| Column | Required | Type | Notes |
|---|---|---|---|
| `ticker` | ✅ | str | Market symbol. Blank ⇒ unresolved: row kept, excluded from priced metrics **and from weights**. |
| `quantity` | ✅ | float | Units held. Fractional allowed. Must be > 0. |
| `name` | — | str | Display label. Cosmetic; never a key. |
| `cost_basis` | — | float | Total paid for the open position, in `base_currency`. Blank ⇒ no P&L for that row. |
| `base_currency` | — | str | Currency of `cost_basis` and of all reporting. Must be uniform. Absent ⇒ app setting (default USD). |
| `asset_class` | — | enum | `EQUITY`, `ETF`, `ETC`, `CRYPTO_ETP`, `CASH`. Absent ⇒ inferred from price metadata. |
| `theme` | — | str | Free-text tag driving theme concentration. Absent ⇒ theme view disabled with an explanatory note. |
| `isin` | — | str | Provenance only. **Never a lookup key** — the app is ticker-keyed. |

**Parsing rules** (each is a test):
- Numbers accept thousands separators: `"1,250"` → `1250`, `"12,500.00"` → `12500.00`.
- Blank and zero are different. Blank `cost_basis` is "unknown"; `0` is "free".
- Duplicate `ticker` rows are **aggregated** — quantities summed, cost bases summed — and the merge is reported, not silently applied.
- Blank lines skipped without error.
- A row failing validation is rejected with `(line_number, ticker, reason)` and surfaced in the UI. One bad row never fails the file.
- A non-uniform `base_currency` fails the **file**, with the conflicting values named.

---

## Test-Driven Development

TDD is the method, not a preference. The loop, per unit of work:

1. **Red** — write the test from the list below. Run it. Confirm it fails *for the stated reason*, not an import error.
2. **Green** — the smallest implementation that passes.
3. **Refactor** — clean up with tests green.
4. Commit test and implementation **together**.

**Rules**
- No production function is written before a failing test names its behaviour.
- A bug fix starts with a test that reproduces it. The test is what proves the fix, and it stays.
- Tests assert **behaviour and numbers**, never internal structure. Renaming a private helper must not break a test.
- Tests are hermetic: **no network**, no clock, no filesystem outside `tmp_path`. A `conftest.py` autouse fixture patches the price client to raise on any real call, so an accidental network test fails loudly rather than passing slowly.
- Every threshold in `risk/rules.py` gets three tests: below, at, and above the boundary.

### The network problem, and why fixtures are frozen

Profiling `concentrated_speculative.csv` against live prices put its largest position at
**24.98%** — 0.02 percentage points under the 25% HIGH threshold. One ordinary trading day flips
that assertion. **Any test that asserts a severity against live prices is flaky by construction.**

So: **`tests/fixtures/prices/` holds frozen daily-close history** (2 years, one CSV per ticker,
plus the FX pairs) captured by `tools/capture_price_fixtures.py`. Unit and integration tests read
only from there. Exactly one test may touch the network:

```python
@pytest.mark.network   # deselected by default: addopts = -m "not network"
def test_price_client_reaches_provider(): ...
```

It asserts reachability and response *shape* — never a numeric threshold.

### Coverage

| Module | Target | Rationale |
|---|---|---|
| `src/ingest/`, `src/risk/`, `src/market/fx.py` | **95%** | A silent wrong number here is worse than a crash |
| `src/market/`, `src/instruments/`, `src/content/` | 85% | |
| Overall | 80% | |
| `src/viz/`, `app.py` | exempt | Verified by eye; no logic permitted |

Coverage is a floor, not a goal — a module at 95% with no boundary tests fails review.

---

## Modules and their test lists

Written in dependency order. Each list is the **red phase** of that module: these tests exist and
fail before its implementation starts.

### `src/ingest/loader.py` — CSV → validated holdings

| # | Test |
|---|---|
| I1 | Minimal valid file (`ticker`, `quantity` only) → parses |
| I2 | Full file with all eight columns → parses, all fields populated |
| I3 | Columns in a different order → identical result |
| I4 | Unknown extra column → preserved, ignored, no warning |
| I5 | UTF-8 BOM → stripped, first column name intact |
| I6 | Quoted field containing a comma (`"Meta Platforms, Inc."`) → intact |
| I7 | Thousands separators (`"1,250"`) → 1250.0 |
| I8 | Blank line mid-file → skipped, not an error |
| I9 | Missing `ticker` header → file-level error naming the column |
| I10 | `quantity` = 0 → row rejected, reason "quantity must be positive" |
| I11 | `quantity` < 0 → row rejected, same reason |
| I12 | `quantity` non-numeric → row rejected, reason names the value |
| I13 | Blank `ticker` → row **kept**, marked unresolved (not a rejection) |
| I14 | Blank `cost_basis` → row kept, `cost_basis is None`, not `0.0` |
| I15 | Duplicate ticker → aggregated: quantities summed, cost bases summed, merge reported |
| I16 | Duplicate ticker where one has blank `cost_basis` → merged basis is `None`, not a partial sum |
| I17 | Mixed `base_currency` values → **file** rejected, both values named |
| I18 | One bad row among good rows → good rows survive; rejection carries the source line number |
| I19 | `malformed.csv` end-to-end → exactly 3 holdings, 5 rejections |
| I20 | Empty file (header only) → empty result, not a crash |

### `src/market/fx.py` — currency conversion

| # | Test |
|---|---|
| F1 | Same currency → rate exactly 1.0, no lookup attempted |
| F2 | USD → EUR at a known rate → correct value |
| F3 | **`GBp` (pence) → base** → divides by 100 relative to `GBP`. The `SGLN.L` trap: mishandled, gold shows as ~900% of `balanced_index`. |
| F4 | `GBP` and `GBp` produce results differing by exactly 100× |
| F5 | Unknown currency code → typed error naming the code, never a silent 1.0 |
| F6 | FX series aligned to price series by date; a missing FX day forward-fills from the last known rate |
| F7 | Forward-fill never reaches backwards in time (no lookahead) |
| F8 | FX rate used is reported with its timestamp |

### `src/market/prices.py` — history fetch and cache

| # | Test |
|---|---|
| P1 | Known ticker → series with expected length and no NaN closes |
| P2 | Unresolvable ticker → typed `UnresolvedTicker`, never an empty series that reads as zero |
| P3 | Fewer than 60 trading days → flagged `insufficient_history`, series still returned |
| P4 | Cache hit → provider not called a second time (asserted on a spy) |
| P5 | Cache respects its TTL and is keyed by `(ticker, range)` |
| P6 | Provider raising → typed error surfaced, not swallowed |

### `src/risk/metrics.py` — the numbers

Hand-computed 3-asset fixture with known covariance, so a failure points at the formula.

| # | Test |
|---|---|
| M1 | Annualized volatility matches hand calculation to 6dp |
| M2 | Portfolio volatility of perfectly correlated assets equals the weighted average |
| M3 | Portfolio volatility of uncorrelated equal-weight assets is strictly below that average |
| M4 | Beta against itself = 1.0 |
| M5 | Beta of a 2× leveraged series = 2.0 |
| M6 | Max drawdown of a monotonically rising series = 0 |
| M7 | Max drawdown of a known peak-trough series matches by hand |
| M8 | VaR₉₅ ≤ CVaR₉₅ always (property test over random series) |
| M9 | Downside deviation of an all-positive-returns series = 0 |
| M10 | Correlation matrix is symmetric with a unit diagonal |
| M11 | A single-position portfolio → correlation metrics return `None`, not NaN or a crash |
| M12 | A position with a constant price (zero variance) → no division-by-zero; volatility 0, beta `None` |
| M13 | **`FRCB` at $0.0004 on a €1,065 basis** → −100% return handled; no `inf`, no `ZeroDivisionError` |
| M14 | Positions flagged `insufficient_history` are excluded from every metric in this module |

### `src/risk/concentration.py`

| # | Test |
|---|---|
| C1 | Weights sum to 1.0 ± 1e-9 |
| C2 | **Unresolved and unpriced rows are excluded from the weight denominator** — otherwise concentration is understated |
| C3 | HHI of an equal-weight N portfolio = 1/N |
| C4 | HHI of a single position = 1.0 |
| C5 | Effective position count = 1/HHI |
| C6 | Top-5 share of a 3-position portfolio = 1.0, not an error |
| C7 | Theme concentration groups correctly and ignores blank themes |
| C8 | Currency exposure groups by *pricing* currency, not base currency |
| C9 | `balanced_index` → HHI ≈ 0.092, max weight ≈ 11.1% (frozen prices) |
| C10 | `concentrated_speculative` → top-5 ≈ 72.8%, crypto **theme** ≈ 35% vs crypto **asset class** ≈ 10.7% |

### `src/risk/rules.py` — metrics → findings

Every threshold gets below/at/above. `at` is explicit because `> 25%` and `>= 25%` are different
rules and the fixture sits at 24.98%.

| # | Test |
|---|---|
| R1 | Weight 24.9% → MEDIUM; 25.0% → MEDIUM (rule is strictly `>`); 25.1% → HIGH |
| R2 | Same triple for each of the 11 thresholds |
| R3 | Findings sorted HIGH → MEDIUM → LOW |
| R4 | Each `Finding.evidence` contains the value that triggered it |
| R5 | Each `Finding.id` is unique within a run |
| R6 | **`balanced_index` produces zero HIGH findings** — the false-positive guard |
| R7 | `concentrated_speculative` produces ≥ 4 HIGH findings including top-5 concentration |
| R8 | `real_scalable` produces a theme-concentration finding that sector concentration does not |
| R9 | Every `Finding.id` has a glossary entry |
| R10 | A metric that is `None` (insufficient data) produces no finding, not a false LOW |

### `src/narrative/explain.py`

| # | Test |
|---|---|
| N1 | With the client mocked, one bullet per finding, in severity order |
| N2 | **Every number in the returned bullets appears in the findings payload** — the anti-hallucination guard, parsed by regex over the rendered text |
| N3 | No API key → template renderer, same bullet count, `mode == "template"` |
| N4 | API error → falls back to templates, surfaces a warning, never raises to the UI |
| N5 | Schema-invalid model response → falls back to templates |
| N6 | Zero findings → a "no material risks flagged" bullet, not an empty section |

### `src/content/glossary.py`

| # | Test |
|---|---|
| G1 | Every displayed metric/KPI/view/finding/flag key has an entry |
| G2 | Every glossary entry corresponds to something displayed (no orphans) |
| G3 | Every entry has non-empty `what` and `how_to_read` |
| G4 | No entry contains recommendation language (`should`, `buy`, `sell`, `trim`, `recommend`) |

### Integration

| # | Test |
|---|---|
| E1 | Each of the three valid fixtures → CSV to rendered findings, no exception |
| E2 | `real_scalable` → 19 holdings, 18 priced, 1 unresolved, 2 insufficient-history |
| E3 | Weights exclude the unresolved SK Hynix GDR yet it appears in the holdings table |
| E4 | Metrics stable across two runs with a warm cache (determinism) |
| E5 | Round-trip: export the parsed portfolio, re-import, identical result |

---

## Tech Stack

| Component | Choice |
|---|---|
| UI | `streamlit` >= 1.40 |
| Data | `pandas` >= 2.2, `numpy` >= 1.26 |
| Market data | `yfinance` >= 0.2.50 |
| Charts | `plotly` >= 5.24 |
| LLM | `anthropic` >= 0.69, model `claude-opus-5` |
| Test | `pytest` >= 8.0, `pytest-cov`, `hypothesis` (property tests M8, C1) |
| Lint | `ruff` >= 0.7 |
| Env | Python 3.12, `venv` + `requirements.txt` |

`claude-opus-5` reasons over ~18 interacting metrics and must not invent numbers. Thinking is on by
default on this model — `max_tokens` must leave headroom.

---

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

streamlit run app.py                       # http://localhost:8501

pytest                                     # network tests deselected by default
pytest -m network                          # the single reachability smoke test
pytest --cov=src --cov-report=term-missing
pytest tests/unit -q                       # fast red-green loop

ruff check . --fix && ruff format .

python tools/build_portfolio_from_scalable.py   # regenerate real_scalable.csv
python tools/capture_price_fixtures.py          # refresh frozen price history
```

`pyproject.toml` sets `addopts = "-m 'not network' --strict-markers"`.

---

## Project Structure

```
portfolio-risk-tracker/
├── app.py                      → Streamlit: layout only, zero logic
├── SPEC.md
├── pyproject.toml              → pytest, ruff, coverage config
├── requirements.txt
├── .env.example
├── src/
│   ├── ingest/
│   │   ├── schema.py           → the CSV contract; column spec + enums
│   │   ├── parsing.py          → numbers, blanks, separators
│   │   └── loader.py           → CSV → (holdings, rejections, merges)
│   ├── instruments/
│   │   └── resolver.py         → ticker validation + user corrections, persisted
│   ├── market/
│   │   ├── prices.py           → history fetch + on-disk cache
│   │   ├── fx.py               → FX series, GBp handling, native → base
│   │   └── metadata.py         → sector, asset class, long name
│   ├── risk/
│   │   ├── metrics.py          → volatility, beta, drawdown, VaR/CVaR, correlation
│   │   ├── concentration.py    → weights, HHI, sector/theme/currency exposure
│   │   ├── trends.py           → 50/200 DMA, 52w-high distance
│   │   └── rules.py            → metrics → Findings; all thresholds in one dict
│   ├── narrative/
│   │   ├── client.py           → Anthropic client construction
│   │   ├── templates.py        → deterministic fallback renderer
│   │   └── explain.py          → findings → bullets
│   ├── content/
│   │   └── glossary.py         → ⓘ definitions
│   ├── viz/
│   │   ├── charts.py           → Plotly figures
│   │   └── info.py             → ⓘ affordance
│   └── store.py                → local persistence under data/
├── tools/                      → repo utilities; NOT imported by src/
│   ├── build_portfolio_from_scalable.py
│   └── capture_price_fixtures.py
├── data/                       → git-ignored: portfolio.csv, prices cache, ticker_fixes.json
└── tests/
    ├── conftest.py             → autouse no-network guard
    ├── unit/                   → mirrors src/
    ├── integration/
    └── fixtures/
        ├── portfolios/         → the four CSVs + README (built)
        └── prices/             → frozen daily closes + FX
```

**Enforced by test:** `src/` must not import `tools/`, and `app.py` must contain no arithmetic.

---

## Analysis Design

### Section 1 — Portfolio distribution

One chart, segmented control:

| View | Chart | Notes |
|---|---|---|
| By holding | Horizontal bar, sorted desc | Value + %; beyond 15 collapses to "Other" |
| By asset class | Donut | Equity / ETF / ETC / Crypto ETP / Cash |
| By sector | Donut | From price metadata; ETFs → `Diversified` |
| By theme | Donut | From the `theme` column; disabled with a note if absent |
| By currency | Donut | Pricing currency, not base |

Bar for holdings (a 19-position pie is unreadable), donut for low-cardinality views. KPI row:
total value, cost basis, unrealized P&L, position count, largest-currency exposure %.

### Section 2 — Risks

Computed deterministically; the LLM only rephrases.

**Concentration** — position weights, largest position, top-5, HHI + effective position count,
sector / theme / asset-class concentration.

**Volatility & downside** — per-position and portfolio volatility, beta, max drawdown, VaR₉₅,
CVaR₉₅, downside deviation.

**Diversification quality** — correlation matrix, average pairwise correlation, count of pairs
above 0.8.

**Currency** — exposure by pricing currency; FX contribution to return and to volatility.
`real_scalable` is EUR-reported but USD-dominated; `balanced_index` spans four currencies.

**Thematic overlap** — the finding sector classification cannot produce. In
`concentrated_speculative`, crypto is 10.7% by asset class and ~35% by theme once `COIN`, `MSTR`
and `RIOT` are counted; in `real_scalable`, 8 of 19 positions are AI/semiconductor including two
thematic ETFs holding names already held directly. Driven by the user's own `theme` column —
honest and inspectable, rather than an unreliable auto-classifier.

**Market trend** — price vs 50/200 DMA, distance from 52-week high, weighted share below 200 DMA.

**Liquidity & data quality** — average dollar volume, position vs volume, insufficient history,
unresolved tickers, rejected rows, merged duplicates, price and FX staleness.

**Thresholds** — one dict at the top of `rules.py`:

| Finding | HIGH | MEDIUM |
|---|---|---|
| Single position weight | > 25% | > 15% |
| Top-5 share | > 70% | > 55% |
| Sector concentration | > 40% | > 30% |
| Theme concentration | > 45% | > 30% |
| Single-currency exposure | > 80% | > 60% |
| Portfolio volatility | > 30% | > 20% |
| Max drawdown | > 40% | > 25% |
| Avg pairwise correlation | > 0.75 | > 0.6 |
| Beta | > 1.4 | > 1.2 |
| Crypto allocation | > 20% | > 10% |
| Below 200 DMA (weighted) | > 60% | > 40% |

All comparisons strictly `>`. R1/R2 pin that down at each boundary.

**Narrative** — findings → JSON → `claude-opus-5` under a system prompt limiting it to (a) only
the supplied numbers, (b) one bullet per finding in severity order, (c) exposure described, never
a trade recommended. Structured outputs (`output_config.format`, schema
`{bullets:[{severity,text,tickers}]}`) so rendering never breaks on formatting drift. No key ⇒
deterministic templates, every risk still shown, mode stated in the UI.

---

## Metric Information Layer (ⓘ)

**No number renders without a glossary entry**, enforced by tests G1–G4 in both directions.

```python
@dataclass(frozen=True)
class GlossaryEntry:
    label: str
    what: str                    # one line: what it measures
    how_to_read: str             # one line: what a high/low value means here
    formula: str | None = None
    caveat: str | None = None
```

`how_to_read` does the real work: "standard deviation of daily returns scaled by √252" teaches
nothing; "above ~20% means a 20% swing in a year is ordinary, not alarming" does.

| Surface | Affordance |
|---|---|
| KPI tiles | `st.metric(..., help=...)` |
| Metric tables | `st.column_config` `help` on the header |
| Section / chart headers | `st.popover("ⓘ")` (headings take no `help`) |
| Risk bullets | ⓘ → definition, threshold, triggering value |
| View selector | `help` describing all five breakdowns |

ⓘ targets ≥24×24px, keyboard-reachable, Escape-dismissible. **The tooltip never carries
information found nowhere else.**

### Glossary content

**KPIs** — `total_value` (market value of priced holdings in base currency; excludes unpriced —
the timestamp says how stale) · `cost_basis` (total paid for what you still hold; blank for rows
without one) · `unrealized_pnl` (value − basis, before tax and fees) · `position_count` (a rough
proxy only — 19 positions with 8 in one theme is less diversified than 8 across five) ·
`currency_exposure` (share of value in the largest pricing currency).

**Views** — `by_holding` (top bar = largest single point of failure) · `by_asset_class` (whether
your risk is one type of thing wearing different names) · `by_sector` (**understates** true
exposure: thematic ETFs land in `Diversified` — read with the theme view) · `by_theme` (catches
what sector cannot: an ETF and the stocks it holds are one bet, not two) · `by_currency` (you
report in one currency but may own another).

**Concentration** — `position_weight` (>15% materially drives returns, >25% dominates) ·
`top5_share` (>55% and the rest are close to decorative) · `hhi` (1/N when even, 1.0 when all in
one; `1÷HHI` is the effective number of positions — *caveat:* counts positions, ignores
correlation) · `sector` (sectors fall together, so 40% behaves like one large position —
*caveat:* understated when thematic ETFs sit in `Diversified`) · `theme` (survives the ETF blind
spot — *caveat:* only as good as your tags, which is why they're yours) · `asset_class`.

**Volatility & downside** — `volatility_position` (~15% typical for a broad index, 40%+ is a
high-variance single name) · `volatility_portfolio` (usually below the average of its holdings —
that gap is diversification working; if it isn't much lower, they move together. *Caveat:*
backward-looking) · `beta` (>1.2 is amplified market risk — *caveat:* only market-linked risk;
gold and crypto can show low beta and still be very risky) · `max_drawdown` (the worst stretch
this portfolio actually lived through — could you have held through it? *Caveat:* history, not
worst case) · `var_95` (on the worst day in 20 expect to lose at least this — a threshold, not a
ceiling) · `cvar_95` (your typical bad-day loss when one arrives; always worse than VaR and the
more honest of the two) · `downside_deviation` (upside swings don't inflate it).

**Diversification** — `correlation_matrix` (blocks of high values are clusters that fall together)
· `avg_correlation` (>0.6 and holdings that look separate are largely one bet — *caveat:*
correlations rise in crises, so calm-market diversification partly evaporates when needed) ·
`high_corr_pairs` (each pair is effectively one position held twice).

**Currency** — `exposure_by_currency` (a rate move changes your total with no company doing
anything) · `fx_contribution_to_return` (separates "the stock went up" from "your currency went
down" — identical on a statement) · `fx_contribution_to_volatility` (minor next to equity risk
until concentration is high).

**Trend** — `dma_50` / `dma_200` (momentum and the conventional trend line — *caveat:* signals,
not forecasts) · `high_52w_distance` (−10% routine, −30%+ means something changed) ·
`below_200dma_weighted` (>40% and weakness is broad, not one name).

**Data quality** — `insufficient_history` (<60 trading days: excluded from volatility, beta,
drawdown, VaR and correlation, still counted in value) · `unresolved_ticker` (no symbol: shown at
cost, excluded from priced metrics **and from weights**, so concentration isn't distorted) ·
`rejected_rows` (rows that failed validation, with reasons — listed so you can confirm nothing
real was dropped) · `merged_duplicates` (the same ticker on multiple lines, combined) ·
`price_staleness` · `fx_rate` (the rate every conversion used; a different rate shifts every
figure on the page).

**Severity** — `high` (past where it materially shapes outcomes: worth a deliberate decision, not
necessarily a change) · `medium` (elevated, often fine if intentional) · `low` (context, noted for
completeness).

Each finding's ⓘ also shows its **threshold** and **triggering value**: *"fired because theme
concentration is 47%, above the 45% HIGH threshold."*

**Tone** — second person, present tense. Name the mechanism, not the mathematics. Formulas only
where they build trust (HHI, VaR). No recommendations: "above 25% one position dominates your
outcome" is description; "you should trim it" is advice, and G4 fails the build on it.

---

## Code Style

Type-hinted, dataclass-based, pure functions. No global state. Streamlit caching on I/O
boundaries only.

```python
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Severity = Literal["HIGH", "MEDIUM", "LOW"]


@dataclass(frozen=True)
class Finding:
    """A single risk observation with the numbers that produced it."""

    id: str
    severity: Severity
    title: str
    evidence: dict[str, float]
    affected_tickers: tuple[str, ...]


def concentration_findings(
    weights: pd.Series,
    *,
    high: float = 0.25,
    medium: float = 0.15,
) -> list[Finding]:
    """Flag positions large enough to dominate portfolio outcomes.

    Args:
        weights: Position weights indexed by ticker, summing to 1.0.
        high: Weight above which a position is a HIGH severity finding.
        medium: Weight above which a position is a MEDIUM severity finding.
    """
    findings: list[Finding] = []
    for ticker, weight in weights.sort_values(ascending=False).items():
        severity: Severity | None = (
            "HIGH" if weight > high else "MEDIUM" if weight > medium else None
        )
        if severity is None:
            break  # sorted desc — nothing below this crosses a threshold
        findings.append(
            Finding(
                id=f"concentration.position.{ticker}",
                severity=severity,
                title=f"{ticker} is {weight:.1%} of the portfolio",
                evidence={"weight": float(weight)},
                affected_tickers=(ticker,),
            )
        )
    return findings
```

Conventions: `snake_case` functions, `PascalCase` classes, `SCREAMING_SNAKE` constants.
Keyword-only arguments for anything tunable. Docstrings on public functions — one summary line,
`Args:` only where the name isn't self-evident. Money is `float` in base currency internally;
formatting at render time only. No bare `except`; failures return typed results the UI displays,
never a silent `None`. Line length 100, `ruff format`.

**The `GBp` trap** deserves its own function and its own tests (F3, F4) — Yahoo quotes some LSE
instruments in pence, and treating that as pounds overstates the position 100×:

```python
def to_base(amount: float, *, native: str, base: str, rates: dict[str, float]) -> float:
    """Convert `amount` from `native` currency into `base`.

    `GBp` is pence, not pounds — one hundredth of `GBP`. Yahoo returns it for
    several LSE-listed instruments (e.g. SGLN.L).
    """
    if native == "GBp":
        return to_base(amount / 100.0, native="GBP", base=base, rates=rates)
    if native == base:
        return amount
    try:
        return amount / rates[native]
    except KeyError as exc:
        raise UnknownCurrencyError(native) from exc
```

**Anthropic call shape:**

```python
response = client.messages.create(
    model="claude-opus-5",
    max_tokens=8000,           # thinking is ON by default on Opus 5 — leave headroom
    output_config={"format": {"type": "json_schema", "schema": BULLETS_SCHEMA}},
    system=RISK_NARRATIVE_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": json.dumps(findings_payload)}],
)
```

No `temperature`, `top_p`, or `budget_tokens` — all rejected on Opus 5.

---

## Boundaries

**Always**
- Write the failing test first; commit test and implementation together.
- Compute every number in Python; the LLM only rephrases.
- Ship a glossary entry with every displayed number.
- Show rejected rows with a reason and a source line number.
- Exclude unpriced and unresolved rows from the weight denominator.
- Label prices and FX rates with their fetch timestamp.
- Render the "not financial advice" disclaimer on the analysis page.
- Run `pytest` and `ruff check` before calling a task done.

**Ask first**
- Adding a paid or authenticated data source.
- Changing the portfolio CSV contract.
- Adding a dependency beyond the stack table.
- Any write outside `data/` or the project directory.
- Sending portfolio contents anywhere other than the Anthropic API.

**Never**
- Write production code with no failing test naming its behaviour.
- Let a unit or integration test touch the network.
- Assert a severity against live prices.
- Import `tools/` from `src/`.
- Let the LLM compute, estimate, or fill in a missing metric.
- Produce buy/sell recommendations or position sizing advice.
- Fabricate prices, FX rates, or ticker mappings — mark unavailable instead.
- Treat `GBp` as `GBP`.
- Commit an API key, a real portfolio CSV, or anything from `data/`.
- Put information *only* in a tooltip.

---

## Success Criteria

1. `streamlit run app.py` starts clean on a fresh venv.
2. All three valid fixtures load and reach rendered findings without an exception.
3. `real_scalable.csv` → 19 holdings, 18 priced, 1 unresolved, 2 insufficient-history; the unresolved GDR is visible in the table and absent from the weights.
4. `malformed.csv` → exactly 3 accepted holdings and 5 rejections, each with a reason and line number.
5. **`balanced_index.csv` produces zero HIGH findings** (false-positive guard).
6. `concentrated_speculative.csv` produces ≥ 4 HIGH findings including top-5 concentration, and its crypto **theme** figure exceeds its crypto **asset-class** figure.
7. `SGLN.L` in `balanced_index` values at roughly 9–10% of the portfolio, not ~900% (GBp handled).
8. Section 1 renders all five breakdowns; each sums to 100% ± 0.1%.
9. Section 2 renders bullets sorted HIGH → MEDIUM → LOW, each showing its triggering number.
10. Every number in a bullet traces to a `Finding.evidence` value (test N2).
11. Every displayed number exposes a working ⓘ; glossary and displayed key sets match both ways.
12. With `ANTHROPIC_API_KEY` unset, the full risk list renders via templates and the UI says so.
13. Unresolved tickers are correctable in-app; a symbol returning no history is rejected on entry.
14. `pytest` passes with no network access available at all.
15. Coverage meets the per-module floors.
16. Restarting reloads the last portfolio, ticker corrections and cached prices.
17. Upload to rendered bullets under 30 seconds on a warm cache.

---

## Build deltas (v3 as-built)

Five decisions changed during implementation. Each was driven by evidence, not preference.

1. **Donuts became bars.** The spec called for donuts on the low-cardinality breakdowns. The
   data-viz anti-pattern catalogue is explicit that a donut is for part-to-whole *at a glance*,
   ≤6 segments, and never for comparing close values — which asset-class and theme breakdowns
   are. All five views are ranked horizontal bars, one hue (eight hues for a single measure is
   the most common form error). The palette was run through the validator: all checks pass with
   a contrast WARN, whose stated relief — visible labels plus a table view — both ship.

2. **A blank ticker is kept, not rejected.** The spec contradicted itself: test I13 said keep,
   the `malformed.csv` table said reject. The real data settled it — the SK Hynix GDR is a
   genuine holding with a real quantity and cost basis and no market symbol. `malformed.csv`
   therefore yields **4 accepted holdings and 3 rejections**, not 3 and 5.

3. **`convert_series` takes a currency mapping, not one series.** The original signature only
   worked when the reporting currency was EUR; a USD-base portfolio holding a EUR-quoted ETF
   would have raised. Both legs now route through the pivot.

4. **`asset_class` inference cannot detect an ETC** (open question 2, now answered with
   evidence). The provider reports `IGLN.L`/`SGLN.L`/`ISLN.L` — physical metal ETCs — as
   `EQUITY`, and `BITC.SW`/`IBIT` as `ETF`. The CSV column always wins; inferred values are
   flagged as inferred.

5. **`sector` is an optional CSV column**, mirroring `theme`, rather than provider metadata.
   The chart endpoint carries no sector, and fabricating a mapping would violate this spec's
   own boundary. The view degrades with an explanatory note when the column is absent.

**Two bugs the tests caught that reasoning did not:** `Analysis` lacked the `as_of` attribute
the page reads — every logic test passed while the page crashed, which is why a UI-contract
test now exists — and `convert_series`'s non-EUR base path was dead code that only surfaced
when tests were written for it.

**Result:** 411 tests, 99% coverage, lint clean, all four fixtures rendering through the real
app with no exception.

---

## Open Questions

1. **Default base currency** when a file omits `base_currency`. Spec says USD as the neutral default; your own data is EUR. Alternative: infer from the majority pricing currency of the resolved tickers. Cheap to change.
2. **`asset_class` inference** when the column is absent. Price metadata gives a `quoteType` (`EQUITY`, `ETF`, `CRYPTOCURRENCY`) that covers most cases but won't distinguish an ETC from an ETF, which matters for the crypto and precious-metals rules. Accept the coarser split, or require the column?
3. **Benchmark for beta.** Default is a base-currency-converted S&P 500. For `balanced_index` (global, multi-currency) MSCI World would be the fairer comparison. Expose as a setting with a per-portfolio default?
4. **Risk thresholds.** The table is calibrated for a moderately diversified retail portfolio. Your real portfolio trips several at MEDIUM. Tune now, or after seeing the first real run?

---

## Next Phases

**Phase 2 — Plan:** `tasks/plan.md`. Critical path `ingest → market/fx → market/prices → risk/metrics → risk/concentration → risk/rules → narrative → viz`, each gated on its test list going green.

**Phase 3 — Tasks:** `tasks/todo.md`, one module per task, each stating its test list, its verify command, and its files. No task touches more than ~5 files.

**Phase 4 — Implement:** strict red-green-refactor. First task is `tools/capture_price_fixtures.py` plus `tests/conftest.py`, because until price fixtures are frozen and the no-network guard is in place, no other test can be trusted.
