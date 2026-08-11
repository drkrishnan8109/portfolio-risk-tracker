"""Asset-class resolution.

The provider's instrument type is too coarse to be trusted on its own. Measured against
the captured fixtures, Yahoo reports:

* `IGLN.L`, `SGLN.L`, `ISLN.L` — physical gold and silver **ETCs** — as `EQUITY`
* `BITC.SW`, `IBIT` — bitcoin **ETPs** — as `ETF`

Both matter, because the precious-metals and crypto rules key off asset class. So the
`asset_class` column in the portfolio CSV always wins, and anything inferred is marked
as inferred so the UI can say so.
"""

from __future__ import annotations

#: Provider instrument type -> our asset class. Deliberately incomplete: there is no
#: mapping to ETC because no provider value identifies one.
_QUOTE_TYPE_MAP = {
    "EQUITY": "EQUITY",
    "ETF": "ETF",
    "MUTUALFUND": "ETF",
    "CRYPTOCURRENCY": "CRYPTO_ETP",
}


def infer_asset_class(quote_type: str | None) -> str | None:
    """Best-effort asset class from the provider's instrument type.

    Returns None when the type is unmappable (`INDEX`, `CURRENCY`, unknown). Never
    returns `ETC` — that distinction is not derivable from provider metadata.
    """
    if not quote_type:
        return None
    return _QUOTE_TYPE_MAP.get(quote_type.upper())


def resolve_asset_class(
    *, declared: str | None, quote_type: str | None
) -> tuple[str | None, bool]:
    """Decide a holding's asset class.

    Args:
        declared: The `asset_class` value from the portfolio CSV, if any.
        quote_type: The provider's instrument type.

    Returns:
        (asset_class, inferred) — `inferred` is True when the value came from provider
        metadata rather than the file, so the UI can flag it as a guess.
    """
    if declared:
        return declared.upper(), False
    return infer_asset_class(quote_type), True
