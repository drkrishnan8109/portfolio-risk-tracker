"""Findings to plain-English bullets.

The model rephrases; it never computes. Two guards enforce that:

1. The prompt supplies the complete findings payload and forbids new figures.
2. Every number in the returned text is checked against the numbers we supplied. A
   bullet containing an unsupported figure is a hallucinated one, and the whole response
   is discarded in favour of the deterministic templates.

Guard 2 is the important one — a prompt instruction is a request, a check is a
guarantee. In a financial readout an invented number is the one failure a reader cannot
catch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from src.narrative.templates import Bullet, render
from src.risk.rules import Finding

MODEL = "claude-opus-5"
MAX_TOKENS = 8000

#: Tolerance in percentage points when matching a rendered figure to a supplied one.
NUMBER_TOLERANCE = 0.15

SYSTEM_PROMPT = """\
You turn a portfolio risk analysis into plain-English bullets for a private investor.

Rules, in priority order:
1. Use ONLY the numbers in the supplied findings. Never compute, estimate, round to a
   different value, or introduce any figure that is not present in the payload.
2. Write exactly one bullet per finding, preserving the order given.
3. Describe the exposure and why it matters. Never recommend an action - no buying,
   selling, trimming or rebalancing advice.
4. Second person, present tense, one or two sentences per bullet. Plain words over
   jargon; if you use a technical term, say what it means in the same sentence.
5. Keep each finding's key figure in its bullet so the reader can see what triggered it.
"""

BULLETS_SCHEMA = {
    "type": "object",
    "properties": {
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                    "text": {"type": "string"},
                    "tickers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["severity", "text", "tickers"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["bullets"],
    "additionalProperties": False,
}

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Narrative:
    bullets: list[Bullet]
    mode: Literal["model", "template"]
    warning: str | None = None


def payload_for(findings: list[Finding]) -> dict:
    """The exact JSON the model is given. Also the allow-list for the number check."""
    return {
        "findings": [
            {
                "id": f.id,
                "kind": f.kind,
                "severity": f.severity,
                "statement": f.title,
                "evidence": f.evidence,
                "threshold": f.threshold,
                "tickers": list(f.affected_tickers),
            }
            for f in findings
        ]
    }


def _allowed_numbers(findings: list[Finding]) -> set[float]:
    """Every figure the model may legitimately quote, on both the raw and percent scale."""
    allowed: set[float] = set()
    for finding in findings:
        values = list(finding.evidence.values())
        if finding.threshold is not None:
            values.append(finding.threshold)
        for value in values:
            allowed.add(round(float(value), 4))
            allowed.add(round(float(value) * 100, 4))
    return allowed


def ungrounded_numbers(text: str, allowed: set[float]) -> list[float]:
    """Figures in `text` that match nothing we supplied."""
    offenders: list[float] = []
    for token in _NUMBER.findall(text):
        try:
            value = float(token)
        except ValueError:  # pragma: no cover - regex guarantees parseability
            continue
        if not any(abs(value - candidate) <= NUMBER_TOLERANCE for candidate in allowed):
            offenders.append(value)
    return offenders


def explain(
    findings: list[Finding],
    *,
    client=None,
    model: str = MODEL,
) -> Narrative:
    """Render findings as bullets, using the model when one is available.

    Falls back to deterministic templates when there is no client, the call fails, the
    response does not match the schema, or any figure in the response is ungrounded.
    """
    if not findings:
        return Narrative(bullets=render([]), mode="template")
    if client is None:
        return Narrative(bullets=render(findings), mode="template")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            output_config={"format": {"type": "json_schema", "schema": BULLETS_SCHEMA}},
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": json.dumps(payload_for(findings), default=str)}
            ],
        )
        parsed = _parse(response)
    except Exception as exc:
        return Narrative(
            bullets=render(findings),
            mode="template",
            warning=f"Risk narrative fell back to templates: {exc}",
        )

    if parsed is None or len(parsed) != len(findings):
        return Narrative(
            bullets=render(findings),
            mode="template",
            warning="Model response did not match the expected shape; used templates instead.",
        )

    allowed = _allowed_numbers(findings)
    for bullet in parsed:
        offenders = ungrounded_numbers(bullet.text, allowed)
        if offenders:
            return Narrative(
                bullets=render(findings),
                mode="template",
                warning=(
                    "Model response contained figures not present in the analysis "
                    f"({offenders}); used templates instead."
                ),
            )

    return Narrative(bullets=parsed, mode="model")


def _parse(response) -> list[Bullet] | None:
    """Pull bullets out of a Messages API response."""
    text = None
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = block.text
            break
    if text is None:
        return None

    try:
        data = json.loads(text)
        items = data["bullets"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    bullets: list[Bullet] = []
    for item in items:
        try:
            bullets.append(
                Bullet(
                    severity=item["severity"],
                    text=item["text"],
                    kind=item.get("kind", "model"),
                    tickers=tuple(item.get("tickers", ())),
                )
            )
        except (KeyError, TypeError):
            return None
    return bullets
