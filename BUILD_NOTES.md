# Build notes

A record of how this project was built with an AI coding assistant: what was asked, what
changed along the way, what the process caught, and what it did not.

Written after the fact but from the actual session, including the parts that went wrong.

---

## 1. Project overview

**Portfolio Risk Tracker** — a Streamlit app that takes a CSV of current holdings and returns
two things: what the portfolio is made of (allocation, switchable across five breakdowns) and
what could hurt it (ranked, numeric risk findings, each with an ⓘ explaining how to read it).

The defining architectural constraint: **every number is computed in Python; the language model
only rephrases.** With no API key the app renders the identical set of findings from
deterministic templates. An LLM you can unplug without losing information is a deliberate
design choice for a tool whose output a reader cannot independently verify.

| | |
|---|---|
| Source | 3,611 lines across `src/` and `app.py` |
| Tests | 2,823 lines · **431 tests** (429 offline, 2 network-marked) · **99% coverage** |
| Fixtures | 42 price symbols × 2 years ≈ 20,105 daily closes, frozen |
| Stack | Streamlit, pandas, NumPy, Plotly, yfinance, Anthropic SDK, pytest, ruff |
| Deployed | Streamlit Community Cloud, auto-redeploying from `main` |

### What it measures

Concentration (position weights, top-5 share, HHI, effective position count), volatility and
downside (annualised volatility, beta, max drawdown, VaR/CVaR at 95%, downside deviation),
diversification quality (correlation matrix, average pairwise correlation, near-identical
pairs), currency exposure, thematic overlap, and trend context (50/200-day averages, distance
from 52-week high).

Eleven thresholds turn those into HIGH/MEDIUM findings, all declared in one dictionary so the
entire risk policy is reviewable in one place.

---

## 2. Datasets used

### 2.1 A real brokerage transaction export (private)

The starting point was a real Scalable Capital transaction export: **1,863 rows** spanning
2022-09 to 2026-08, semicolon-delimited, German decimal format, EUR-denominated, keyed by ISIN
rather than ticker.

Analysis of it produced:

| Property | Value |
|---|---|
| Rows | 1,863 total → **1,640 executed** (196 cancelled, 16 rejected, 10 expired, 1 pending) |
| Instruments | 56 distinct ISINs → **19 open positions**, 37 fully closed |
| Oversells | none — FIFO reconciles end to end |

**Three traps in this file, each of which silently corrupts cost basis:**

1. **A custody migration.** Fourteen `Security transfer` rows out of the old custodian and
   fourteen back in, netting to exactly zero per instrument. Processed naively they read as
   *sales*: FIFO closes every lot, books a phantom gain, and re-opens positions at
   migration-date prices — resetting cost basis to near-current values and understating real
   gains. The most dangerous defect in the dataset, and wrong in the flattering direction.
2. **A recorded stock split** encoded as a `Corporate action` row pair (−4 shares at one price,
   +40 at one tenth). Quantity survives naive handling; lot dates do not, which breaks FIFO
   ordering for later sales.
3. **An unrecorded stock split.** A holding's price fell tenfold across five days with no
   corporate-action row at all. Found by scanning for price discontinuities between consecutive
   trades, not by reading the file.

This file and the portfolio derived from it are **git-ignored**. Tests that depend on the
derived fixture skip with a hint, so a fresh clone still passes.

### 2.2 Three synthetic portfolio fixtures

Built deliberately to sit at different points on the risk scale:

| Fixture | Max weight | Top-5 | Largest theme | Role |
|---|---:|---:|---|---|
| `balanced_index.csv` | 11.1% | 48.4% | 20.7% | **Negative case** — should raise no HIGH findings |
| (private real portfolio) | 20.4% | 63.2% | ~41% | Real-world messiness |
| `concentrated_speculative.csv` | 25.0% | 72.8% | 43.5% | **Positive case** — several HIGH findings |

Plus `malformed.csv`: eight rows, each asserting one parser behaviour (duplicate ticker, zero
quantity, negative quantity, non-numeric, blank line, thousands separators, blank cost basis).

The negative case turned out to be the more valuable of the two synthetic files. A risk tool
that fires red warnings on a genuinely diversified portfolio is producing false positives, and a
tool that cries wolf gets ignored. Most test suites only assert that a thing fires; this one
also asserts that it *stays quiet*.

`balanced_index.csv` also carries a deliberate trap: a London-listed instrument quoting in
**pence**, not pounds.

### 2.3 Frozen price history

42 symbols (every fixture ticker, a benchmark, three FX pairs), two years of daily closes,
captured once and committed — about 20,105 rows.

The reason is specific and measurable. `concentrated_speculative.csv`'s largest position sits at
**24.98%**, two hundredths of a percentage point below the 25% HIGH threshold. Against live
prices, that assertion flips on any ordinary trading day. Any test asserting a severity against
live data is flaky by construction.

An autouse pytest fixture patches the socket layer, so an accidental network call fails loudly
rather than passing slowly. Exactly two tests may reach the provider, and they assert
reachability and response *shape* — never a number.

---

## 3. Prompts used

Reproduced in order, verbatim. Notable throughout: they are short, and most of the detail came
from the assistant asking clarifying questions or from the data itself contradicting an
assumption.

**1 — the brief**
> I want to build a portfolio risk tracker using streamlit. I have a csv of all the
> transactions. The app should allow two different kinds of data to be uploaded - either all
> historical transactions or a csv of current portfolio. There has to be a tab to "Prepare
> portfolio csv" so that if historical transactions are uploaded, the current posrtfolio csv can
> be prepared from it. Once the portfolio csv is avaialble, the app should analyse the
> portfolio, check market trands and do a detailed analysis to find our risk of my portfolio.
> The app should have 2 sections - one a chart shoing my portfolio distribution and another
> giving risks in bullet points. First, prepare a spec for the same for my approval.

**2 — the ⓘ requirement**
> For each of the metrics and categories, have ab information - the 'i' symbol usually used in
> UIs to describe what the metrics does

**3 — the real data** (CSV attached)
> Here is an example csv of transactions:

**4 — a scope challenge**
> Is this an agentic use case?

**5 — the pivot**
> ok, the app should be a generalised one. So let us keep this conversion from historical
> transaction to csv part out of the app, and expect the users to just upload the csv of current
> portfolio. Do the following steps: 1. Remove the prepartion of historical transaction to csv of
> portfolio part... 2. Prepare a portfolio csv from the historical transactions i gave. Its for
> testing with this real data. 3. Prepare 2 different datasets similar to the csv portfolio
> prepared in step 2, its for testing purposes. 4. Use test driven development

**6 — build**
> ok, now let us prepare the code for the app

**7 — a mid-build question**
> /btw what are fixtures

**8 — verification**
> how to test UI manually now

**9 — a feature**
> Add error pop up window if the csv format is malformed or any issues with the file.

**10 — documentation**
> Prepare a ReadMe on for this app and how to run the app.

**11 — publishing**
> create a git repo and push this. Add real_csv to git ignore

**12 — privacy follow-up**
> update read me and remove any info related to real_scalable.csv. No test required after this
> update.

**13 — a deployment bug**
> i have deployed a streamlit app for this one. Now it always shows the last portfolio i
> uploaded, how to clean it

**14 — deployment mechanics**
> i assume i dont have to keep deploying again, and streamlit would pick it from latest git
> code ?

### On prompting style

The prompts that produced the most work were the shortest. *"Use test driven development"* is
five words and set the shape of 2,823 lines of tests. *"Is this an agentic use case?"* is a
one-line challenge that prevented a whole category of over-engineering.

What made them effective was that each one either **set a constraint** or **supplied evidence**,
rather than describing an implementation. The single highest-value prompt was #3 — attaching the
real file — because it invalidated four assumptions in a single step, which no amount of
discussion would have surfaced.

---

## 4. Iterations

### Spec v1 → v2: the real data destroyed four assumptions

v1 was written before the data arrived, and assumed US markets, USD, ticker-keyed,
comma-delimited. The actual export was **EUR, ISIN-keyed, semicolon-delimited with German
decimals, from a German broker**. Four of five core assumptions wrong.

v2 was a rewrite, not a patch. It also added two things the data made obvious that the brief had
not mentioned:

- **Currency risk.** The portfolio reports in EUR but is ~79% USD-denominated. That is a
  measurable exposure and it was invisible in v1.
- **Thematic overlap.** Eight of nineteen positions were AI/semiconductor — including two
  thematic ETFs holding names already owned directly. Sector classification files those ETFs
  under their own bucket, so the chart shows diversification that is not there.

### Spec v2 → v3: cutting the largest feature

Prompt #5 removed the transaction-to-portfolio converter, the most complex part of the design.
The reasoning recorded at the time: each broker export carries its own traps (this one had
three), so owning that surface turns a risk-analysis project into a broker-integration project.

The converter was **demoted rather than deleted** — it survives as a repo tool whose only job is
regenerating one test fixture, with an enforced rule that `src/` never imports from `tools/`.

This was the highest-value decision in the project, and it came from the user, not the
assistant.

### Chart form: donuts → bars

The spec called for donut charts on the low-cardinality breakdowns. Consulting visualization
guidance during implementation flipped this: a donut is for part-to-whole *at a glance*, capped
at ~6 segments, and specifically wrong for comparing close values — which asset-class and theme
breakdowns are. All five views became ranked horizontal bars in a **single hue**; using eight
colours for a single measure is decoration, not encoding. The palette was run through a
validator rather than eyeballed.

### An API design that only worked by accident

`convert_series` passed all 23 of its tests while only working when the reporting currency
happened to be EUR. A USD-reporting portfolio holding a EUR-quoted ETF would have raised. The
tests all used an EUR base, so the broken path was never exercised. Caught by writing a test for
the case rather than by reading the code.

### The privacy scrub took three passes

1. Git-ignore the real CSV — as asked.
2. Discovered that ignoring the CSV alone does not make holdings private: the amounts were still
   in the docs and in a test assertion. Scrubbed those.
3. **After pushing**, an audit of the pushed branch found three more leaks: the app's own CSV
   template used a real position, and two test files used a real cost basis. Fixed, history
   rewritten, force-pushed.

Step 3 is the failure worth recording. The assistant had stated that nothing with real holdings
would go up — having checked the documentation but not the application code or the tests. The
claim was made before the audit that would have justified it.

### Deployment broke a documented assumption

The spec said "local single-user app, no auth, no multi-user, no hosting". The app persisted the
last portfolio to `data/portfolio.csv` so it reloaded on the next visit — reasonable for a local
tool.

Deployed to a public URL, that same feature became a **cross-user data leak**: the file lives on
the server, so one visitor's holdings were served to the next. Fixed by moving to
`st.session_state` (per browser session, never on disk), with a warning added to the persistence
helper so it cannot be reintroduced.

The bug was not in the code. It was in an assumption that stopped being true the moment the
context changed, and nothing in the code said so out loud.

---

## 5. What the process caught

Four defects were found by tests that reasoning alone had missed:

| Defect | How it surfaced |
|---|---|
| `Analysis` had no `as_of` attribute the page reads | 400+ logic tests passed while the page crashed on load. Found by running the app headlessly. A UI-contract test now guards it. |
| `convert_series` non-EUR base was dead code | Only exposed by writing the test for it |
| `beta` returned `None` for short series | The guard was right (a 5-point beta is noise); the *test data* was too short. The test was wrong, not the code. |
| VaR of 0 looked like a bug | With one −10% day in twenty, the 5th percentile genuinely lands above zero. The expectation was wrong; the code was right. |

Two of those four were **incorrect tests, not incorrect code**. Writing the test first forces the
expectation to be stated before the implementation can quietly define it — and sometimes reveals
that the expectation was the thing in error.

A contradiction in the spec surfaced the same way: one test said a blank ticker should be kept,
a table two sections later said it should be rejected. The real data settled it — an untradeable
holding with a genuine quantity and cost basis is a *holding*, not an invalid row.

---

## 6. Learnings and observations

**Real data beats discussion.** Four assumptions survived a detailed written spec and died within
minutes of the actual file arriving. If there is a real input, get it early — the spec written
before it is a draft regardless of how careful it is.

**Ask the data, don't ask the model.** The claim "yfinance can distinguish an ETC from an ETF"
was testable in about thirty seconds, and false: physical gold ETCs report as `EQUITY`, bitcoin
ETPs as `ETF`. That measurement turned an open question into a settled design rule (the CSV
column wins; guesses are flagged as guesses). Several other decisions were settled by
measurement rather than assertion — the 24.98% boundary, the ISIN-to-ticker resolutions, the
GBp/GBP distinction.

**Verify before claiming, not after.** The privacy leak was not a technical failure — the fix was
three small edits. It was a *sequencing* failure: the assurance came before the audit. When
stakes are asymmetric, the check belongs before the sentence, not after it.

**Deterministic beats generative where the reader cannot verify.** Every number is computed in
Python, and the narrative layer additionally checks each figure in the model's output against
the supplied findings — any unsupported number discards the whole response in favour of
templates. A prompt instruction is a request; a check is a guarantee. In a financial readout, an
invented number is the one failure a reader has no way to catch.

**"Is this agentic?" is worth asking out loud.** The honest answer here was no: a deterministic
pipeline with one LLM call at the leaf, and even that call optional. Adding an agent would have
handed model latitude to arithmetic that currently has none, in a domain where the user cannot
check the output. The most useful thing an assistant can do with an architecture question is
sometimes to argue *against* the more impressive answer.

**Test isolation is a design constraint, not hygiene.** The 24.98% boundary made "tests must not
hit the network" a hard requirement rather than a preference, and that single decision shaped the
repository layout: a repository protocol, two implementations, frozen fixtures, and an autouse
guard that makes accidental live calls fail loudly.

**Scope reduction was the highest-leverage change.** Removing the transaction converter cut the
most complex and most trap-laden part of the design and left a coherent tool. It came from the
user. An assistant will generally build what is asked; deciding what *not* to build remained a
human contribution throughout.

**Documentation drifts silently.** Three doc bugs were found only by re-reading: a fixture README
still claiming a blank ticker was rejected (contradicting the implemented behaviour and a
passing test), an expected-outcome count that was wrong, and install instructions naming a
Python binary that resolved into an unrelated project's virtualenv. None of them would have
failed a test. The glossary layer avoided this class of problem by construction — a test asserts
that displayed metrics and explanations match in both directions, so an unexplained number fails
the build.

---

## 7. What would be done differently

- **Attach the real data with the first prompt.** It would have skipped an entire spec revision.
- **Decide the privacy boundary before the first commit**, not after pushing. History rewriting
  was cheap here only because the repository was twenty minutes old and had one collaborator.
- **State deployment intent in the spec.** "Local single-user" was written down and then quietly
  invalidated by deploying. An assumption worth writing down is worth re-checking when the
  context changes.
- **Split runtime and development dependencies.** `requirements.txt` currently installs the test
  toolchain on the deployment target — harmless, but it slows every cold start for no benefit.

---

## 8. Repository map

```
app.py                    layout only — no arithmetic
src/ingest/               CSV → validated holdings, plus file diagnostics
src/market/               prices, FX, metadata; live.py is the only network module
src/risk/                 metrics, concentration, trends, rules, valuation, engine
src/narrative/            findings → bullets, with the anti-hallucination guard
src/content/glossary.py   one explanation per displayed number
src/viz/                  Plotly figures and the ⓘ affordance
tools/                    repo utilities, never imported by src/
tests/fixtures/           example portfolios + frozen price history
```

| Test module | Tests | Covers |
|---|---:|---|
| `test_glossary.py` | 136 | Every metric has an explanation, in both directions |
| `test_edge_paths.py` | 48 | Error and degenerate paths |
| `test_metrics.py` | 35 | Risk statistics against hand-computed expectations |
| `test_ingest.py` | 33 | The CSV contract |
| `test_rules.py` | 28 | Threshold boundaries: below, at, above |
| `test_concentration.py` | 26 | Weights, HHI, group exposure |
| `test_fx.py` | 26 | Currency conversion, including the pence trap |
| `test_end_to_end.py` | 25 | CSV in, findings out |
| `test_prices.py` | 22 | History, caching, asset-class metadata |
| `test_narrative.py` | 21 | Bullets and the anti-hallucination guard |
| `test_diagnostics.py` | 19 | What counts as a file problem |
| `test_live.py` | 10 | Live wiring, against a fake repository |
| `test_network_smoke.py` | 2 | Opt-in provider reachability |
