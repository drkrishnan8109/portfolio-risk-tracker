"""Tests N1-N6 — bullets, and the guard that the model never invents a number."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.narrative.explain import (
    Narrative,
    explain,
    payload_for,
    ungrounded_numbers,
)
from src.narrative.templates import NO_FINDINGS_TEXT, render
from src.risk.rules import Finding


def finding(fid="concentration.position.NVDA", kind="position_weight", severity="HIGH", **kw):
    return Finding(
        id=fid,
        kind=kind,
        severity=severity,
        title=kw.get("title", "NVDA is 30.0% of the portfolio"),
        evidence=kw.get("evidence", {"weight": 0.30}),
        affected_tickers=kw.get("tickers", ("NVDA",)),
        threshold=kw.get("threshold", 0.25),
    )


# --- fake client ---------------------------------------------------------------------


@dataclass
class FakeBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list


class FakeClient:
    """Stands in for `anthropic.Anthropic`, recording the request it was given."""

    def __init__(self, payload=None, raises=None, raw=None):
        self._payload = payload
        self._raises = raises
        self._raw = raw
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        body = self._raw if self._raw is not None else json.dumps(self._payload)
        return FakeResponse(content=[FakeBlock(text=body)])


def bullets_payload(*texts, severity="HIGH"):
    return {"bullets": [{"severity": severity, "text": t, "tickers": []} for t in texts]}


# --- N1: shape ------------------------------------------------------------------------


def test_n1_one_bullet_per_finding_in_order():
    findings = [
        finding(severity="HIGH"),
        finding(fid="concentration.top5", kind="top5_share", severity="MEDIUM",
                title="Your five largest positions are 60.0% of the portfolio",
                evidence={"top5_share": 0.60}, threshold=0.55, tickers=()),
    ]
    client = FakeClient(
        bullets_payload("NVDA is 30.0% of your portfolio.", "Your top five are 60.0%.")
    )
    result = explain(findings, client=client)
    assert result.mode == "model"
    assert len(result.bullets) == 2
    assert [b.severity for b in result.bullets] == ["HIGH", "HIGH"]


def test_n1_request_carries_the_findings_payload():
    client = FakeClient(bullets_payload("NVDA is 30.0% of your portfolio."))
    explain([finding()], client=client)
    sent = json.loads(client.calls[0]["messages"][0]["content"])
    assert sent["findings"][0]["id"] == "concentration.position.NVDA"
    assert sent["findings"][0]["evidence"]["weight"] == 0.30


def test_n1_request_uses_structured_outputs_and_the_right_model():
    client = FakeClient(bullets_payload("NVDA is 30.0% of your portfolio."))
    explain([finding()], client=client)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in call, "rejected on Opus 5"
    assert "top_p" not in call


# --- N2: the anti-hallucination guard --------------------------------------------------


def test_n2_grounded_numbers_pass():
    allowed = {0.30, 30.0, 0.25, 25.0}
    assert ungrounded_numbers("NVDA is 30.0% of the portfolio", allowed) == []


def test_n2_invented_number_is_detected():
    allowed = {0.30, 30.0}
    assert ungrounded_numbers("NVDA is 47.2% of the portfolio", allowed) == [47.2]


def test_n2_model_response_with_an_invented_figure_falls_back():
    """The failure a reader cannot catch, so the code catches it instead."""
    client = FakeClient(bullets_payload("NVDA is 47.2% of your portfolio, up from 12.1%."))
    result = explain([finding()], client=client)
    assert result.mode == "template"
    assert "not present in the analysis" in result.warning


def test_n2_every_number_in_model_output_traces_to_the_payload():
    findings = [finding()]
    client = FakeClient(bullets_payload("NVDA is 30.0% of the portfolio, above the 25.0% line."))
    result = explain(findings, client=client)
    assert result.mode == "model"

    allowed = set()
    for item in payload_for(findings)["findings"]:
        allowed.update(round(float(v), 4) for v in item["evidence"].values())
        allowed.update(round(float(v) * 100, 4) for v in item["evidence"].values())
        allowed.add(round(float(item["threshold"]) * 100, 4))
    for bullet in result.bullets:
        assert ungrounded_numbers(bullet.text, allowed) == []


def test_n2_tolerance_allows_reasonable_rounding():
    allowed = {20.37}
    assert ungrounded_numbers("about 20.4% of the portfolio", allowed) == []


# --- N3: no key -------------------------------------------------------------------------


def test_n3_without_a_client_templates_are_used():
    result = explain([finding()], client=None)
    assert result.mode == "template"
    assert len(result.bullets) == 1
    assert "NVDA" in result.bullets[0].text


def test_n3_template_mode_still_reports_every_risk():
    findings = [finding(), finding(fid="market.beta", kind="beta", severity="MEDIUM",
                                   title="Portfolio beta is 1.30", evidence={"beta": 1.3},
                                   threshold=1.2, tickers=())]
    result = explain(findings, client=None)
    assert len(result.bullets) == len(findings)


def test_n3_template_bullets_include_interpretation():
    """A template bullet still explains what the number means."""
    bullet = explain([finding()], client=None).bullets[0]
    assert "dominates" in bullet.text or "drives" in bullet.text


# --- N4-N5: failure modes ----------------------------------------------------------------


def test_n4_api_error_falls_back_without_raising():
    client = FakeClient(raises=RuntimeError("503 overloaded"))
    result = explain([finding()], client=client)
    assert result.mode == "template"
    assert "503" in result.warning
    assert len(result.bullets) == 1


def test_n5_invalid_json_falls_back():
    client = FakeClient(raw="not json at all")
    result = explain([finding()], client=client)
    assert result.mode == "template"
    assert result.warning


def test_n5_wrong_bullet_count_falls_back():
    client = FakeClient(bullets_payload("one", "two", "three"))
    result = explain([finding()], client=client)
    assert result.mode == "template"


def test_n5_missing_required_field_falls_back():
    client = FakeClient({"bullets": [{"severity": "HIGH"}]})
    result = explain([finding()], client=client)
    assert result.mode == "template"


def test_n4_failure_never_raises_to_the_caller():
    for client in [
        FakeClient(raises=ValueError("boom")),
        FakeClient(raw="{}"),
        FakeClient(raw="[]"),
    ]:
        assert isinstance(explain([finding()], client=client), Narrative)


# --- N6: empty ---------------------------------------------------------------------------


def test_n6_no_findings_yields_a_positive_statement():
    result = explain([], client=None)
    assert len(result.bullets) == 1
    assert result.bullets[0].text == NO_FINDINGS_TEXT


def test_n6_no_findings_does_not_call_the_model():
    client = FakeClient(bullets_payload("unused"))
    explain([], client=client)
    assert client.calls == []


def test_render_of_empty_findings():
    assert render([])[0].severity == "LOW"


# --- against a real analysis --------------------------------------------------------------


def test_template_bullets_for_a_real_portfolio(speculative_analysis):
    result = explain(speculative_analysis.findings, client=None)
    assert len(result.bullets) == len(speculative_analysis.findings)
    assert result.bullets[0].severity == "HIGH"


def test_model_bullets_grounded_for_a_real_portfolio(real_analysis):
    """Echo each finding's own statement back: grounded by construction, so mode stays 'model'."""
    texts = [f.title for f in real_analysis.findings]
    client = FakeClient(bullets_payload(*texts, severity="MEDIUM"))
    result = explain(real_analysis.findings, client=client)
    assert result.mode == "model", result.warning
