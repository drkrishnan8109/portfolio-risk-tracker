"""Rebuild `tests/fixtures/portfolios/real_scalable.csv` from a Scalable Capital export.

A one-off repo utility, **not part of the app**. Nothing in `src/` imports it. Its only
job is regenerating one test fixture, kept so that fixture is reproducible rather than
mysterious.

The export hides three traps, each of which silently corrupts cost basis if ignored:

1. **Status.** Only `Executed` rows are real. Cancelled, Rejected, Expired and Pending
   orders never happened.
2. **A custody migration** (2025-12-05/06). Fourteen `Security transfer` rows out of the
   old custodian and fourteen back in, netting per-ISIN to zero. Read as trades they
   close every lot, book a phantom gain, and reset cost basis to December-2025 prices.
3. **Splits.** NVIDIA's 10:1 is recorded as a `Corporate action` row pair. Netflix's
   10:1 is *not recorded at all* — it was found by looking for price discontinuities
   (EUR 977.30 -> EUR 95.66 across five days in November 2025) and is applied from the
   table below.

Usage:
    python tools/build_portfolio_from_scalable.py path/to/export.csv
    SCALABLE_EXPORT=path/to/export.csv python tools/build_portfolio_from_scalable.py

The output is git-ignored: it contains real holdings and cost basis.
"""

from __future__ import annotations

import argparse
import collections
import csv
import os
import sys
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 28

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "portfolios" / "real_scalable.csv"

#: Set SCALABLE_EXPORT to avoid passing the path every time. No default is baked in:
#: the export is personal data and its location should not live in version control.
ENV_SOURCE = "SCALABLE_EXPORT"

BUY_TYPES = {"Buy", "Savings plan"}
TRANSFER_WINDOW_DAYS = 5

#: Splits absent from the export, found by price-discontinuity analysis.
UNRECORDED_SPLITS: dict[str, list[tuple[str, Decimal]]] = {
    "US64110L1061": [("2025-11-13", Decimal(10))],  # Netflix 10:1
}

#: ISIN -> (ticker, asset class, theme). Every ticker was verified against live price
#: history: the symbol resolves, its name matches the instrument, and history is
#: non-empty. Blank ticker = deliberately unresolved (no symbol exists).
INSTRUMENTS: dict[str, tuple[str, str, str]] = {
    "US67066G1040": ("NVDA", "EQUITY", "AI/Semiconductors"),
    "US02079K1079": ("GOOG", "EQUITY", "Big Tech"),
    "IE00BGV5VN51": ("XAIX.DE", "ETF", "AI/Semiconductors"),
    "IE00B4NCWG09": ("ISLN.L", "ETC", "Precious Metals"),
    "IE00B4ND3602": ("IGLN.L", "ETC", "Precious Metals"),
    "US5949181045": ("MSFT", "EQUITY", "Big Tech"),
    "US30303M1027": ("META", "EQUITY", "Big Tech"),
    "DE0007030009": ("RHM.DE", "EQUITY", "Defence"),
    "IE000X59ZHE2": ("AIFS.DE", "ETF", "AI/Semiconductors"),
    "US7134481081": ("PEP", "EQUITY", "Consumer Staples"),
    "US8740391003": ("TSM", "EQUITY", "AI/Semiconductors"),
    "GB00BLD4ZL17": ("BITC.SW", "CRYPTO_ETP", "Crypto"),
    "US11135F1012": ("AVGO", "EQUITY", "AI/Semiconductors"),
    "US0079031078": ("AMD", "EQUITY", "AI/Semiconductors"),
    "US78392B2060": ("SKHY", "EQUITY", "AI/Semiconductors"),
    "US64110L1061": ("NFLX", "EQUITY", "Big Tech"),
    "US84615Q1031": ("SPCX", "EQUITY", "Space"),
    "US33616C1009": ("FRCB", "EQUITY", "Legacy/Distressed"),
    "US78392B1070": ("", "EQUITY", "AI/Semiconductors"),  # SK Hynix GDR: no symbol
}

OUTPUT_COLUMNS = [
    "ticker",
    "name",
    "quantity",
    "cost_basis",
    "base_currency",
    "asset_class",
    "theme",
    "isin",
]


def parse_de(raw: str | None) -> Decimal | None:
    """Parse a German-formatted decimal: '1.234,56' -> 1234.56. Blank -> None."""
    text = (raw or "").strip()
    if not text:
        return None
    return Decimal(text.replace(".", "").replace(",", "."))


def read_executed(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [r for r in csv.DictReader(handle, delimiter=";") if r["status"] == "Executed"]
    rows.sort(key=lambda r: (r["date"], r["time"]))
    return rows


def pair_migration_transfers(rows: list[dict]) -> set[int]:
    """Match each outgoing custody transfer to its incoming twin.

    Returns the ids of rows to ignore entirely. Raises if any transfer is unmatched,
    because guessing at an unpaired transfer is exactly how cost basis gets corrupted.
    """
    transfers = [r for r in rows if r["type"] == "Security transfer"]
    paired: set[int] = set()

    for out_row in transfers:
        shares = parse_de(out_row["shares"])
        if id(out_row) in paired or shares is None or shares >= 0:
            continue
        for in_row in transfers:
            if id(in_row) in paired or in_row is out_row:
                continue
            in_shares = parse_de(in_row["shares"])
            if in_row["isin"] == out_row["isin"] and in_shares == -shares:
                paired.update({id(out_row), id(in_row)})
                break

    unmatched = [r for r in transfers if id(r) not in paired]
    if unmatched:
        raise SystemExit(
            f"{len(unmatched)} unmatched Security transfer row(s); refusing to guess. "
            f"First: {unmatched[0]['date']} {unmatched[0]['isin']}"
        )
    return paired


def split_table(rows: list[dict]) -> dict[str, list[tuple[str, Decimal]]]:
    """Recorded corporate-action splits, plus the unrecorded ones."""
    grouped: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row["type"] == "Corporate action":
            grouped[(row["isin"], row["date"])].append(row)

    splits: dict[str, list[tuple[str, Decimal]]] = collections.defaultdict(list)
    for (isin, date), pair in grouped.items():
        outgoing = next(r for r in pair if parse_de(r["shares"]) < 0)
        incoming = next(r for r in pair if parse_de(r["shares"]) > 0)
        ratio = parse_de(incoming["shares"]) / -parse_de(outgoing["shares"])
        by_price = parse_de(outgoing["price"]) / parse_de(incoming["price"])
        if abs(ratio - by_price) > Decimal("0.01"):
            raise SystemExit(f"{isin} {date}: share ratio {ratio} disagrees with price {by_price}")
        splits[isin].append((date, ratio))

    for isin, events in UNRECORDED_SPLITS.items():
        splits[isin].extend(events)
    return splits


def build_holdings(rows: list[dict]) -> tuple[dict[str, tuple[Decimal, Decimal]], dict[str, str]]:
    """FIFO lot ledger. Returns {isin: (quantity, cost_basis)} and {isin: latest name}."""
    ignored = pair_migration_transfers(rows)
    splits = split_table(rows)

    lots: dict[str, collections.deque] = collections.defaultdict(collections.deque)
    names: dict[str, str] = {}
    applied: dict[str, set[str]] = collections.defaultdict(set)

    def apply_splits(isin: str, upto: str) -> None:
        for date, ratio in splits.get(isin, []):
            if date <= upto and date not in applied[isin]:
                for lot in lots[isin]:
                    lot[1] *= ratio  # same money, more shares
                applied[isin].add(date)

    for row in rows:
        if row["assetType"] != "Security" or id(row) in ignored:
            continue
        if row["type"] == "Corporate action":
            continue

        isin, date = row["isin"], row["date"]
        quantity = parse_de(row["shares"])
        names[isin] = row["description"]
        apply_splits(isin, date)

        if row["type"] in BUY_TYPES:
            cost = abs(parse_de(row["amount"]) or Decimal(0)) + (parse_de(row["fee"]) or Decimal(0))
            lots[isin].append([date, quantity, cost])
        elif row["type"] == "Sell":
            remaining = quantity
            while remaining > 0 and lots[isin]:
                lot = lots[isin][0]
                taken = min(remaining, lot[1])
                lot[2] -= lot[2] * (taken / lot[1])
                lot[1] -= taken
                remaining -= taken
                if lot[1] <= Decimal("0.0000001"):
                    lots[isin].popleft()
            if remaining > Decimal("0.0000001"):
                raise SystemExit(f"oversell: {isin} on {date}")

    for isin in list(lots):
        apply_splits(isin, "9999-99-99")

    holdings = {
        isin: (sum(lot[1] for lot in deque), sum(lot[2] for lot in deque))
        for isin, deque in lots.items()
        if sum(lot[1] for lot in deque) > Decimal("0.000001")
    }
    return holdings, names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        default=os.environ.get(ENV_SOURCE),
        help=f"Scalable Capital transaction export (or set ${ENV_SOURCE})",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if args.source is None:
        raise SystemExit(
            f"Pass the transaction export path, or set ${ENV_SOURCE}.\n"
            "  python tools/build_portfolio_from_scalable.py ~/Downloads/export.csv"
        )
    if not args.source.exists():
        raise SystemExit(f"Transaction export not found: {args.source}")

    rows = read_executed(args.source)
    holdings, names = build_holdings(rows)
    print(f"{len(rows)} executed rows -> {len(holdings)} open positions")

    unmapped = sorted(set(holdings) - set(INSTRUMENTS))
    if unmapped:
        raise SystemExit(f"No instrument mapping for: {', '.join(unmapped)}")

    ordered = sorted(holdings.items(), key=lambda item: -item[1][1])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for isin, (quantity, basis) in ordered:
            ticker, asset_class, theme = INSTRUMENTS[isin]
            writer.writerow(
                {
                    "ticker": ticker,
                    "name": names[isin],
                    "quantity": f"{quantity.normalize():f}",
                    "cost_basis": f"{basis:.2f}",
                    "base_currency": "EUR",
                    "asset_class": asset_class,
                    "theme": theme,
                    "isin": isin,
                }
            )

    total = sum(basis for _, basis in holdings.values())
    print(f"total cost basis EUR {total:,.2f}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
