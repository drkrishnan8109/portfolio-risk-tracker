# Portfolio test fixtures

Three CSVs in the app's one and only input format. Two are valid portfolios chosen to sit at
different points on the risk scale; the third is deliberately broken.

All tickers were verified against live price history at capture time — symbol resolves, name
matches the intended instrument, and history is non-empty. `XYZQ.FAKE` is the one exception,
included precisely because it does *not* resolve.

| File | Positions | Base | Purpose |
|---|---:|---|---|
| `balanced_index.csv` | 11 | EUR | Diversified index investor — the **negative case**: almost nothing should fire |
| `concentrated_speculative.csv` | 11 | USD | Concentrated, crypto-heavy — the **positive case**: many findings should fire |
| `malformed.csv` | 8 rows | USD | Validation only. Every row is a distinct parser case, several invalid. |

---

## Schema

| Column | Required | Notes |
|---|---|---|
| `ticker` | ✅ | Market symbol. Blank means unresolved — the row is kept but excluded from priced metrics. |
| `quantity` | ✅ | Units held. Fractional allowed. Must be > 0. |
| `name` | — | Display label. Cosmetic; never used as a key. |
| `cost_basis` | — | Total paid for the open position, in `base_currency`. Blank ⇒ no P&L for that row. |
| `base_currency` | — | Currency the `cost_basis` is expressed in and the currency all reporting uses. Must be uniform across the file. Absent ⇒ app setting. |
| `asset_class` | — | `EQUITY`, `ETF`, `ETC`, `CRYPTO_ETP`, `CASH` |
| `theme` | — | Free-text tag. Drives theme concentration. |
| `isin` | — | Provenance only. Never a lookup key — the app is ticker-keyed. |

Unknown columns are preserved and ignored (`malformed.csv` carries a `broker_note` column to prove it).

---

## What each fixture exercises

### `balanced_index.csv` — the negative case

Eleven positions, none above ~11%, spread across global equity, US equity, EM, bonds, gold and
five single stocks in unrelated sectors. **Nothing should trip a concentration threshold.** A rule
engine that fires HIGH findings here is producing false positives, which is the failure mode that
makes a risk tool ignorable.

Also carries the **`GBp` trap**: `SGLN.L` quotes in *pence*, not pounds. Converting it as if it
were GBP overstates that position by 100×. If the fixture's gold sleeve shows up near 900% of the
portfolio, that is the bug.

Four pricing currencies against an EUR base: EUR, USD, CHF, GBp.

### `concentrated_speculative.csv` — the positive case

Eleven positions, USD base, deliberately over-concentrated:

- **Top-5 = 72.8%** — above the 70% HIGH threshold.
- **Largest position 24.98%** — a hair *under* the 25% HIGH threshold, so it should resolve MEDIUM. This is an intentional boundary case; see the warning below.
- **Crypto by asset class ≈ 10.7%** (`IBIT` alone) but **crypto by theme ≈ 35%** once `COIN`, `MSTR` and `RIOT` are counted. The gap between those two numbers is the whole argument for the theme layer — asset-class classification says "modest crypto sleeve", the theme layer says "a third of the portfolio rides bitcoin".
- **Two blank `cost_basis` values** (`RIOT`, `SMCI`) — P&L must degrade for those rows only, not for the file.
- **One unresolvable ticker** — `XYZQ.FAKE`.

### `malformed.csv` — validation only

Never load this as a portfolio. Each row asserts one parser behaviour, and the header is in a
different column order to prove order-independence:

| Row | Expectation |
|---|---|
| `AAPL` ×2 | Duplicate ticker — **aggregate**: quantity 65, cost basis 12,020.00, reported as a merge |
| `MSFT` qty 0 | Reject — zero quantity |
| `GOOG` qty −15 | Reject — negative quantity |
| `META` qty `abc` | Reject — non-numeric |
| blank ticker | **Accept** — an unresolved holding, not an invalid one |
| `PEP` `"1,250"` / `"12,500.00"` | **Accept** — thousands separators parse to 1250 / 12500.00 |
| (blank line) | Skip silently, not an error |
| `JNJ` blank `cost_basis` | Accept — P&L unavailable for this row only |

Expected outcome: **4 accepted holdings** (AAPL merged, the blank-ticker row, PEP, JNJ) and
**3 rejections**, each with a reason and its source row number.

---

## ⚠️ Tests must not hit the network

The weights above were measured against live prices and **will drift**. `concentrated_speculative`
sits 0.02pp below a HIGH threshold today; a normal day's move flips it. Any test asserting a
severity against live data is flaky by construction.

Unit and integration tests therefore run against **frozen price fixtures** captured alongside
these files (see `tests/fixtures/prices/`), never against yfinance. Only a single, explicitly
marked `@pytest.mark.network` smoke test is allowed to touch the real API, and it asserts
reachability and schema — never a numeric threshold.

## Regenerating

```bash
python tools/capture_price_fixtures.py    # refreshes tests/fixtures/prices/
```

Refreshing prices changes expected metric values; update the expectation tables in the same commit.
