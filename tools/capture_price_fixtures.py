"""Capture frozen daily price history for every ticker used by the test fixtures.

Tests must never hit the network: a portfolio's largest position sits 0.02pp below a
severity threshold, so any assertion made against live prices is flaky by construction.
This tool snapshots history once; the suite reads only the snapshot.

    python tools/capture_price_fixtures.py

Refreshing prices changes expected metric values — update the expectation tables in the
same commit.
"""

from __future__ import annotations

import csv
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIOS = ROOT / "tests" / "fixtures" / "portfolios"
OUT = ROOT / "tests" / "fixtures" / "prices"

BENCHMARKS = ["^GSPC"]
# All cross rates are derived from these EUR-based pairs (see src/market/fx.py).
FX_PAIRS = ["EURUSD=X", "EURCHF=X", "EURGBP=X"]
RANGE = "2y"
UA = {"User-Agent": "Mozilla/5.0"}

socket.setdefaulttimeout(20)


def safe_name(symbol: str) -> str:
    """Filesystem-safe stem for a ticker (`^GSPC` -> `_GSPC`, `EURUSD=X` -> `EURUSD_X`)."""
    return symbol.replace("^", "_").replace("=", "_").replace("/", "_")


def fetch(symbol: str) -> dict | None:
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={RANGE}&interval=1d"
    )
    req = urllib.request.Request(url, headers=UA)
    try:
        payload = json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as exc:
        print(f"  {symbol:12s} HTTP {exc.code}")
        return None
    except Exception as exc:
        print(f"  {symbol:12s} {type(exc).__name__}")
        return None

    chart = payload.get("chart") or {}
    if chart.get("error") or not chart.get("result"):
        print(f"  {symbol:12s} no result")
        return None
    return chart["result"][0]


def tickers_from_fixtures() -> list[str]:
    found: set[str] = set()
    for path in sorted(PORTFOLIOS.glob("*.csv")):
        if path.stem == "malformed":
            continue  # validation fixture; its tickers are covered by the others
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = (row.get("ticker") or "").strip()
                if symbol:
                    found.add(symbol)
    return sorted(found)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = tickers_from_fixtures() + BENCHMARKS + FX_PAIRS
    print(f"capturing {len(symbols)} symbols, range={RANGE}\n")

    meta: dict[str, dict] = {}
    failed: list[str] = []

    for symbol in symbols:
        result = fetch(symbol)
        time.sleep(0.35)
        if result is None:
            failed.append(symbol)
            continue

        stamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows = [
            (
                datetime.fromtimestamp(ts, tz=UTC).date().isoformat(),
                close,
                volumes[i] if i < len(volumes) else None,
            )
            for i, (ts, close) in enumerate(zip(stamps, closes, strict=False))
            if close is not None
        ]
        if not rows:
            print(f"  {symbol:12s} empty series")
            failed.append(symbol)
            continue

        with (OUT / f"{safe_name(symbol)}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "close", "volume"])
            writer.writerows(rows)

        info = result.get("meta", {})
        meta[symbol] = {
            "currency": info.get("currency"),
            "name": info.get("longName") or info.get("shortName"),
            "quote_type": info.get("instrumentType"),
            "exchange": info.get("fullExchangeName"),
            "points": len(rows),
            "first": rows[0][0],
            "last": rows[-1][0],
            "last_close": rows[-1][1],
        }
        print(
            f"  {symbol:12s} {info.get('currency')!s:4s} {len(rows):4d} pts  "
            f"{rows[-1][0]}  {rows[-1][1]}"
        )

    meta_payload = {
        "captured_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "range": RANGE,
        "symbols": meta,
        "failed": failed,
    }
    (OUT / "meta.json").write_text(json.dumps(meta_payload, indent=1) + "\n", encoding="utf-8")

    print(f"\ncaptured {len(meta)} / {len(symbols)}")
    if failed:
        print(f"failed: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
