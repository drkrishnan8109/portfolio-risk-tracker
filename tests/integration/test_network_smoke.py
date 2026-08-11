"""The single test allowed to touch a live provider.

Deselected by default (`addopts = -m "not network"`); run it with `pytest -m network`.

It asserts **reachability and response shape only** — never a numeric threshold. A test
that checked a price or a weight against live data would fail on any ordinary market
move, which is the whole reason the rest of the suite runs on frozen fixtures.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.market.live import build_repository, fx_series_for
from src.market.prices import PriceHistory


@pytest.mark.network
def test_provider_returns_a_usable_history():
    history = build_repository().history("AAPL")

    assert isinstance(history, PriceHistory)
    assert isinstance(history.closes.index, pd.DatetimeIndex)
    assert history.points > 0
    assert history.meta.currency  # a currency is always present
    assert not history.closes.isna().any()


@pytest.mark.network
def test_provider_supplies_the_fx_pairs_the_app_needs():
    fx = fx_series_for(build_repository(), {"USD", "GBp", "CHF"})

    # GBp folds onto GBP rather than requesting a pair that does not exist.
    assert set(fx) == {"USD", "GBP", "CHF"}
    for series in fx.values():
        assert len(series) > 0
