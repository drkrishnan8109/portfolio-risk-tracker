# Portfolio Risk Tracker

Upload a CSV of what you hold. Get back two things:

1. **What the portfolio is made of** — an allocation chart you can switch between holding, asset class, theme, currency and sector.
2. **What could hurt it** — ranked, numeric risk bullets, each with an ⓘ explaining how to read the number and why it fired.

Every figure is computed in Python. Claude only rephrases the findings into plain English, and the app runs completely without it.

---

## Quick start

**Prerequisites:** Python 3.12 or newer, and an internet connection (prices come from Yahoo Finance).

```bash
cd portfolio-risk-tracker

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

streamlit run app.py
```

It opens at **http://localhost:8501**. No API key, no account, no configuration.

Check your Python first if you are unsure:

```bash
python3 -V        # needs 3.12+
```

### Confirm the install is sound

```bash
pytest             # the full suite, a few seconds, no network needed
```

If those pass, every calculation in the app is behaving as specified.

---

## Your first run

The app starts empty. Three example portfolios ship with it, in `tests/fixtures/portfolios/`.
Upload one from the sidebar to see the whole thing working:

| File | What it shows |
|---|---|
| `balanced_index.csv` | A well-diversified portfolio. Should raise **no red findings** — that is the point of it. |
| `concentrated_speculative.csv` | Over-concentrated and crypto-heavy. Several red findings. |
| `malformed.csv` | A deliberately broken file, to see the error dialog. |

Start with `concentrated_speculative.csv`, then switch the chart from **By asset class** to **By theme**. Crypto jumps from ~11% to ~35%. That gap is the single most useful thing this app does; see [Theme beats sector](#theme-beats-sector) below.

A holding with a blank `ticker` is worth seeing too: it stays visible in the file report but is kept out of the percentages, so the position count can exceed the number of bars on the chart.

---

## Using your own portfolio

One CSV. Only `ticker` and `quantity` are required — everything else is optional.

```csv
ticker,name,quantity,cost_basis,base_currency,asset_class,theme,isin
AAPL,Apple Inc.,50,9000.00,USD,EQUITY,Big Tech,US0378331005
IGLN.L,iShares Physical Gold,100,7500.00,USD,ETC,Precious Metals,IE00B4ND3602
,Untraded Holding,10,2000.00,USD,EQUITY,,
```

| Column | Required | Notes |
|---|---|---|
| `ticker` | ✅ | The symbol your data provider uses — `NVDA`, `RHM.DE`, `IGLN.L`, `BITC.SW`. **Leave blank** for something untradeable: the holding stays visible but is excluded from the percentages. |
| `quantity` | ✅ | Units held. Fractional is fine. Must be greater than zero. |
| `name` | | Display label only. |
| `cost_basis` | | Total you paid, in `base_currency`. Leave blank and that row simply has no P&L. |
| `base_currency` | | The currency the whole report is produced in. Must be the same on every row. Omit it and the sidebar setting applies. |
| `asset_class` | | `EQUITY`, `ETF`, `ETC`, `CRYPTO_ETP`, `CASH`. Guessed from market data if absent — but see [the ETC note](#asset-class-cannot-be-guessed-reliably). |
| `theme` | | Free text, entirely yours. Drives the theme breakdown. |
| `isin` | | Kept for your reference; never used to look anything up. |

Column order does not matter, extra columns are ignored, and there is a **Download CSV template** button in the sidebar.

Tips that save time:

- **Finding a ticker:** search it on finance.yahoo.com and use the symbol shown there. European listings carry a suffix — `.DE` Xetra, `.L` London, `.AS` Amsterdam, `.SW` Swiss, `.PA` Paris.
- **Duplicate rows** for the same ticker are added together and reported, so you can paste in separate lots.
- **Themes are worth ten minutes.** They are the only way the app can see that a thematic fund and the stocks it holds are one bet.

---

## When something is wrong with the file

A dialog opens on upload, at one of two levels.

**Blocking** — the file cannot be read at all: a missing `ticker` or `quantity` column, or rows disagreeing about `base_currency`. The dialog says what happened, how to fix it, and offers the template. The message also stays on the page, so closing the dialog does not leave you with a blank screen.

**Non-blocking** — the file loaded, but something was left out: rows rejected, duplicate tickers merged, holdings that could not be priced, too little history for risk metrics, or an asset class that had to be guessed. The analysis is still valid; the dialog tells you what is missing from it.

Silence is the dangerous case. A portfolio quietly missing three rows still produces confident-looking percentages, and nothing on screen would tell you. The dialog opens once per file, a banner stays while issues remain, and **View report** reopens it.

---

## What you get

**Distribution** — allocation by holding, asset class, theme, currency and sector.

**Portfolio statistics** — volatility, beta, maximum drawdown, VaR and CVaR at 95%, concentration (HHI), effective position count, top-5 share, average correlation.

**Risk findings** — eleven thresholds turn those numbers into 🔴 HIGH and 🟠 MEDIUM bullets, each stating the figure that triggered it. Every threshold lives in one dictionary at the top of [`src/risk/rules.py`](src/risk/rules.py), so the entire risk policy is reviewable — and editable — in one place.

Every number on the page has an ⓘ. It explains what the metric measures, how to read a high or low value, and where the metric misleads. On a risk bullet it also shows the threshold and the measured value: *"fired because theme concentration is 41.4%, above the 30.0% MEDIUM threshold."*

### Optional: Claude-written bullets

Without a key you get the same findings rendered from deterministic templates. With one, Claude rewrites them as prose:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

The sidebar tells you which mode is active. The model is never allowed to compute anything: every number in its output is checked against the numbers supplied, and any unsupported figure discards the whole response in favour of templates.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `command not found: streamlit` | The venv is not active. Run `source .venv/bin/activate` first, or use `./.venv/bin/streamlit run app.py`. |
| `Port 8501 is already in use` | Another copy is running. `pkill -f "streamlit run app.py"`, or start on another port: `streamlit run app.py --server.port 8502`. |
| A holding shows under "could not be priced" | The ticker is wrong or unlisted. Check it on finance.yahoo.com and remember the exchange suffix. The holding stays visible either way. |
| Values disagree with my broker | Expected, and small. The app prices from a different venue at a different moment, and converts currencies at its own rate. The exact rate and timestamp are shown under the KPIs. |
| A position looks about 100× too big | A pence-quoted London holding. The app handles `GBp` correctly, so if you see this, please report it — there is a test for exactly this case. |
| Beta shows "—" | Fewer than 20 overlapping days with the benchmark, or the benchmark ticker in the sidebar did not resolve. |
| Everything recalculates slowly | The first load fetches two years of history per holding. It is cached for 15 minutes after that. |
| The app opens showing an old portfolio | The last uploaded file is remembered in `data/portfolio.csv`. Delete it to start clean. |

Nothing you upload leaves your machine, apart from ticker symbols going to Yahoo Finance for prices — and the findings going to Anthropic, only if you set an API key.

---

## Development

```bash
pytest                              # full suite; no network access required
pytest -m network                   # the two opt-in provider smoke tests
pytest --cov=src --cov-report=term-missing
pytest tests/unit -q                # fast loop while editing
ruff check . --fix && ruff format .
```

**Tests never touch the network.** A fixture patches the socket layer, so an accidental live call fails loudly instead of passing slowly. Everything runs against frozen price history in `tests/fixtures/prices/` — two years of daily closes for 42 symbols.

That is not fussiness. The speculative fixture's largest position sits at **24.98%**, two hundredths of a point under the HIGH threshold. Against live prices that assertion flips on any ordinary trading day.

### Layout

```
app.py                    layout only — no arithmetic lives here
src/ingest/               CSV -> validated holdings, and file diagnostics
src/market/               prices, FX, asset-class metadata; live.py is the only network module
src/risk/                 metrics, concentration, trends, rules, valuation, engine
src/narrative/            findings -> bullets, with the anti-hallucination guard
src/content/glossary.py   one explanation per displayed number
src/viz/                  Plotly figures and the ⓘ affordance
tools/                    repo utilities, never imported by src/
tests/fixtures/           example portfolios + frozen prices
```

### Regenerating fixtures

```bash
python tools/capture_price_fixtures.py     # refresh frozen price history
```

Refreshing prices changes expected metric values — update the expectation tables in the same commit.

Personal portfolio files are git-ignored (see `.gitignore`). Any test that depends on one skips
with a hint when it is absent, so a fresh clone passes without it.

---

## Design notes

### Theme beats sector

Sector classification files a thematic ETF in its own bucket, so a portfolio holding NVDA, AMD, TSM **and** two AI ETFs looks diversified — while those ETFs hold the names you already own directly. The theme column, which is yours to write, counts them as the single bet they are.

In the bundled speculative portfolio, crypto is ~11% by asset class and ~35% by theme once `COIN`, `MSTR` and `RIOT` are included. Same portfolio, very different conclusion.

### Unpriced holdings are excluded from the denominator

A holding with no price keeps its row and its cost basis but is left out of every percentage. Counting it at zero would understate every other position and hide concentration — the opposite of what a risk tool is for.

### `GBp` is not `GBP`

Several London instruments quote in **pence**, not pounds. Treating one as the other overstates that position 100× — a 9% gold sleeve would show as 900% of the portfolio. Handled in [`src/market/fx.py`](src/market/fx.py), with tests pinning it down.

### Asset class cannot be guessed reliably

Measured against real market data, the provider reports physical gold and silver **ETCs** as `EQUITY`, and bitcoin **ETPs** as `ETF`. Both matter, because the crypto and precious-metals rules key off asset class. So the `asset_class` column in your file always wins, and anything guessed is flagged as guessed.

### The model never invents a figure

Beyond instructing it not to, every number in Claude's response is checked against the numbers supplied. Any unsupported figure discards the whole response in favour of templates. A prompt instruction is a request; a check is a guarantee — and in a financial readout an invented number is the one failure a reader cannot catch.

### Not financial advice

The app describes exposures. It makes no recommendation, and a test fails the build if advice language — "should", "buy", "sell", "trim", "rebalance" — appears in any explanation.
