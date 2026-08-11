"""Shared test fixtures and the no-network guard.

Every unit and integration test runs against frozen price history. An accidental live
call must fail loudly rather than pass slowly, so `block_network` patches the socket
layer for the whole suite. Tests that genuinely need the provider opt out with
`@pytest.mark.network`, which is deselected by default (see pyproject.toml).
"""

from __future__ import annotations

import csv
import json
import socket
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PORTFOLIOS = FIXTURES / "portfolios"
PRICES = FIXTURES / "prices"


class NetworkAccessAttempted(RuntimeError):
    """Raised when a test tries to open a socket."""


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    """Fail any test that reaches for the network, unless marked `network`."""
    if request.node.get_closest_marker("network"):
        return

    def deny(*args, **kwargs):
        raise NetworkAccessAttempted(
            "Test attempted a network call. Use the frozen fixtures in "
            "tests/fixtures/prices, or mark the test @pytest.mark.network."
        )

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


#: Fixtures derived from real personal financial data. Kept out of version control,
#: so a fresh clone skips the tests that need them rather than failing.
PRIVATE_FIXTURES = {"real_scalable.csv"}

REGENERATE_HINT = (
    "{name} holds real portfolio data and is not in the repo. "
    "Regenerate it with `python tools/build_portfolio_from_scalable.py`, "
    "or ignore this skip - the other fixtures cover the same code paths."
)


def fixture_path(name: str) -> Path:
    """Path to a portfolio fixture, skipping the test when a private one is absent."""
    path = PORTFOLIOS / name
    if not path.exists():
        if name in PRIVATE_FIXTURES:
            pytest.skip(REGENERATE_HINT.format(name=name))
        raise FileNotFoundError(path)
    return path


def _safe_name(symbol: str) -> str:
    return symbol.replace("^", "_").replace("=", "_").replace("/", "_")


@pytest.fixture(scope="session")
def price_meta() -> dict:
    return json.loads((PRICES / "meta.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def frozen_prices() -> dict[str, pd.Series]:
    """Every captured symbol as a close-price Series indexed by date."""
    series: dict[str, pd.Series] = {}
    meta = json.loads((PRICES / "meta.json").read_text(encoding="utf-8"))
    for symbol in meta["symbols"]:
        path = PRICES / f"{_safe_name(symbol)}.csv"
        frame = pd.read_csv(path, parse_dates=["date"])
        series[symbol] = pd.Series(
            frame["close"].to_numpy(), index=pd.DatetimeIndex(frame["date"]), name=symbol
        )
    return series


@pytest.fixture(scope="session")
def frozen_volumes() -> dict[str, pd.Series]:
    volumes: dict[str, pd.Series] = {}
    meta = json.loads((PRICES / "meta.json").read_text(encoding="utf-8"))
    for symbol in meta["symbols"]:
        frame = pd.read_csv(PRICES / f"{_safe_name(symbol)}.csv", parse_dates=["date"])
        volumes[symbol] = pd.Series(
            frame["volume"].to_numpy(), index=pd.DatetimeIndex(frame["date"]), name=symbol
        )
    return volumes


@pytest.fixture
def repo(frozen_prices, frozen_volumes, price_meta):
    """A PriceRepository backed entirely by the frozen fixtures."""
    from src.market.prices import FrozenPriceRepository

    return FrozenPriceRepository(
        closes=frozen_prices, volumes=frozen_volumes, meta=price_meta["symbols"]
    )


@pytest.fixture
def rates(frozen_prices):
    """EUR-based FX rate table taken from the last frozen observation."""
    return {
        "EUR": 1.0,
        "USD": float(frozen_prices["EURUSD=X"].iloc[-1]),
        "CHF": float(frozen_prices["EURCHF=X"].iloc[-1]),
        "GBP": float(frozen_prices["EURGBP=X"].iloc[-1]),
    }


@pytest.fixture
def fx_series(frozen_prices):
    """EUR-based FX series keyed by currency, for time-aligned conversion."""
    return {
        "USD": frozen_prices["EURUSD=X"],
        "CHF": frozen_prices["EURCHF=X"],
        "GBP": frozen_prices["EURGBP=X"],
    }


@pytest.fixture
def portfolios_dir() -> Path:
    return PORTFOLIOS


@pytest.fixture
def real_portfolio() -> Path:
    """The real portfolio fixture, or a skip when it is not present."""
    return fixture_path("real_scalable.csv")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> Path:
    """Helper for building one-off CSVs inside tmp_path."""
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


# --- analysis fixtures ---------------------------------------------------------------


@pytest.fixture
def analyse_fixture(repo, fx_series):
    """Load, value and analyse one of the portfolio fixtures end to end."""
    from src.ingest.loader import load_portfolio
    from src.market.fx import FxRates, convert_series
    from src.risk.engine import analyse
    from src.risk.valuation import value_portfolio

    def _run(name: str):
        loaded = load_portfolio(fixture_path(name))
        portfolio = value_portfolio(
            loaded.holdings,
            repo=repo,
            base_currency=loaded.base_currency,
            fx_series=fx_series,
            fx_rates=FxRates.from_series(fx_series, base=loaded.base_currency),
        )
        benchmark = repo.history("^GSPC")
        benchmark_base = convert_series(
            benchmark.closes,
            native=benchmark.meta.currency,
            base=loaded.base_currency,
            fx=fx_series,
        )
        return analyse(portfolio, benchmark_closes=benchmark_base)

    return _run


@pytest.fixture
def balanced_analysis(analyse_fixture):
    return analyse_fixture("balanced_index.csv")


@pytest.fixture
def speculative_analysis(analyse_fixture):
    return analyse_fixture("concentrated_speculative.csv")


@pytest.fixture
def real_analysis(analyse_fixture):
    return analyse_fixture("real_scalable.csv")


@pytest.fixture
def balanced_inputs(balanced_analysis):
    return balanced_analysis.inputs


@pytest.fixture
def speculative_inputs(speculative_analysis):
    return speculative_analysis.inputs


@pytest.fixture
def real_inputs(real_analysis):
    return real_analysis.inputs
