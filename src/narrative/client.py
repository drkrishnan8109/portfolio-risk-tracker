"""Anthropic client construction.

Returns None rather than raising when no key or no SDK is available: the narrative layer
is optional by design, and the app must run fully without it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientStatus:
    client: object | None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.client is not None

    @property
    def mode_label(self) -> str:
        return "Claude narrative" if self.available else "Template narrative"


def build_client(api_key: str | None = None) -> ClientStatus:
    """Build an Anthropic client if we can, and explain it if we cannot.

    Args:
        api_key: Overrides `ANTHROPIC_API_KEY`. Useful in tests.
    """
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return ClientStatus(None, "No ANTHROPIC_API_KEY set - risk bullets use templates.")

    try:
        import anthropic
    except ImportError:
        return ClientStatus(None, "The anthropic package is not installed - using templates.")

    try:
        return ClientStatus(anthropic.Anthropic(api_key=key))
    except Exception as exc:
        return ClientStatus(None, f"Could not create the Anthropic client: {exc}")
