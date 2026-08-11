"""Tests G1-G4 — the ⓘ contract.

The point of these is that adding a metric without an explanation fails the build, and
a stale entry for a deleted metric is caught too.
"""

from __future__ import annotations

import re

import pytest

from src.content.glossary import (
    DISPLAYED_KEYS,
    FINDING_KIND_KEYS,
    GLOSSARY,
    UnknownGlossaryKey,
    entry,
    for_finding,
    tooltip,
)
from src.risk.rules import THRESHOLDS


def test_g1_every_displayed_key_has_an_entry():
    missing = DISPLAYED_KEYS - set(GLOSSARY)
    assert missing == set(), f"displayed with no explanation: {sorted(missing)}"


def test_g2_every_entry_is_displayed_somewhere():
    orphans = set(GLOSSARY) - DISPLAYED_KEYS
    assert orphans == set(), f"glossary entries nothing renders: {sorted(orphans)}"


@pytest.mark.parametrize("key", sorted(GLOSSARY))
def test_g3_entries_have_substance(key):
    item = GLOSSARY[key]
    assert item.label.strip()
    assert len(item.what.strip()) > 20, "'what' must actually explain the metric"
    assert len(item.how_to_read.strip()) > 20, "'how_to_read' is the half that matters"


@pytest.mark.parametrize("key", sorted(GLOSSARY))
def test_g3_how_to_read_is_not_a_restatement(key):
    item = GLOSSARY[key]
    assert item.how_to_read.strip().lower() != item.what.strip().lower()


#: Advice, not description. The app describes exposure; it never tells anyone what to do.
BANNED = re.compile(r"\b(should|shouldn't|buy|sell|trim|rebalance|recommend\w*|advise\w*)\b", re.I)


@pytest.mark.parametrize("key", sorted(GLOSSARY))
def test_g4_no_recommendation_language(key):
    item = GLOSSARY[key]
    blob = " ".join(filter(None, [item.what, item.how_to_read, item.caveat or ""]))
    found = BANNED.findall(blob)
    assert not found, f"{key} contains advice language: {found}"


def test_g4_the_guard_actually_catches_advice():
    """A canary: if the pattern stopped matching, G4 would pass vacuously."""
    assert BANNED.search("you should trim this position")
    assert BANNED.search("we recommend rebalancing")
    assert not BANNED.search("if you sold everything now")  # 'sold' is description


def test_every_finding_kind_has_a_glossary_entry():
    for kind in THRESHOLDS:
        assert kind in FINDING_KIND_KEYS, f"finding kind {kind!r} has no glossary mapping"
        assert FINDING_KIND_KEYS[kind] in GLOSSARY


def test_finding_kind_lookup_returns_an_entry():
    assert for_finding("position_weight").label == "Position weight"


def test_unknown_key_raises_rather_than_rendering_a_bare_number():
    with pytest.raises(UnknownGlossaryKey):
        entry("does.not.exist")


def test_tooltip_includes_what_and_how_to_read():
    text = tooltip("risk.beta")
    assert "Sensitivity to the benchmark" in text
    assert "How to read it" in text


def test_tooltip_includes_caveat_when_present():
    assert "Caveat" in tooltip("concentration.hhi")


def test_tooltip_omits_caveat_when_absent():
    assert "Caveat" not in tooltip("kpi.total_value")


def test_findings_from_a_real_analysis_all_have_explanations(speculative_analysis):
    for finding in speculative_analysis.findings:
        assert finding.kind in FINDING_KIND_KEYS, f"{finding.id} has no glossary mapping"
        assert for_finding(finding.kind).how_to_read
