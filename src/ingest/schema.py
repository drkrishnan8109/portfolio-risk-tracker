"""The portfolio CSV contract: column spec and the value objects it produces."""

from __future__ import annotations

from dataclasses import dataclass, field

REQUIRED_COLUMNS = ("ticker", "quantity")
OPTIONAL_COLUMNS = ("name", "cost_basis", "base_currency", "asset_class", "theme", "isin")
KNOWN_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

ASSET_CLASSES = ("EQUITY", "ETF", "ETC", "CRYPTO_ETP", "CASH")

DEFAULT_BASE_CURRENCY = "USD"


@dataclass(frozen=True)
class Holding:
    """One position in the portfolio.

    `ticker` may be empty: that is an *unresolved* holding, not an invalid one. The real
    Scalable portfolio contains an SK Hynix GDR with a genuine quantity and cost basis
    but no market symbol. It stays visible, and stays out of every priced metric.
    """

    ticker: str
    quantity: float
    name: str | None = None
    cost_basis: float | None = None
    asset_class: str | None = None
    theme: str | None = None
    isin: str | None = None
    source_lines: tuple[int, ...] = field(default=(), compare=False)

    @property
    def resolved(self) -> bool:
        return bool(self.ticker)


@dataclass(frozen=True)
class Rejection:
    """A row that failed validation, and why."""

    line: int
    ticker: str | None
    reason: str


@dataclass(frozen=True)
class Merge:
    """Two or more rows for the same ticker, combined into one holding."""

    ticker: str
    lines: tuple[int, ...]
    quantity: float
    cost_basis: float | None


@dataclass(frozen=True)
class LoadResult:
    """Everything a load produced: what was accepted, dropped, and combined."""

    holdings: list[Holding]
    rejections: list[Rejection]
    merges: list[Merge]
    base_currency: str

    @property
    def resolved_holdings(self) -> list[Holding]:
        return [h for h in self.holdings if h.resolved]

    @property
    def unresolved_holdings(self) -> list[Holding]:
        return [h for h in self.holdings if not h.resolved]
