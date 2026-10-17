from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas import (
    AlertLevel,
    Briefing,
    Channel,
    Clause,
    ClauseJudgment,
    DocFit,
    Duration,
    Event,
    EventType,
    ExposurePath,
    Feedback,
    MatchResult,
    Playbook,
    Premises,
    Verdict,
)


def make_event() -> Event:
    return Event(
        id="svb_2023",
        title="SVB 사태",
        date=date(2023, 3, 10),
        summary="미국 지역은행 뱅크런",
        type=EventType.banking_stress,
        channels=[Channel.liquidity, Channel.counterparty],
        regions=["US"],
        sectors=["regional_banks"],
        asset_classes=["equity", "bond"],
        entities=["Silicon Valley Bank"],
        duration=Duration.weeks,
        severity=4,
        sources=["https://example.com/svb"],
    )


def make_clause(**kw) -> Clause:
    base = dict(
        clause_id="LIQ-01-C1",
        doc_id="LIQ-01",
        text="단기 유동성 비율이 하한을 밑돌면 현금성 자산을 확보한다.",
        premises=Premises(event_types=[EventType.liquidity_crisis], channels=[Channel.liquidity]),
        actions=["현금성 자산 비중 점검"],
        owner_role="자금운용팀",
    )
    base.update(kw)
    return Clause(**base)


def make_briefing() -> Briefing:
    judgment = ClauseJudgment(
        clause_id="LIQ-01-C1", verdict=Verdict.applicable, evidence_quote="현금성 자산을 확보한다", confidence=0.9
    )
    fit = DocFit(doc_id="LIQ-01", fit_score=1.0, n_applicable=1, n_partial=0, n_not=0, n_uncertain=0, judgments=[judgment])
    return Briefing(
        run_id="run-1",
        event=make_event(),
        alert_level=AlertLevel.ALERT,
        match=MatchResult(event_id="svb_2023", doc_fits=[fit], gaps=[Channel.counterparty]),
        exposure_top=[
            ExposurePath(nodes=["Inst", "Fund", "Bank"], weight=0.1, relevance=0.8, uncertainty=0.3, risk_score=0.068)
        ],
        actions_to_check=["현금성 자산 비중 점검 (자금운용팀)"],
        evidence_refs=["LIQ-01-C1"],
        trace_id="trace-1",
    )


@pytest.mark.parametrize(
    "model",
    [
        make_event(),
        make_clause(),
        Playbook(
            doc_id="LIQ-01", title="유동성 위기 매뉴얼", version="1.0", year=2020,
            origin_event="covid_2020", synthetic=True, clauses=[make_clause()],
        ),
        make_briefing(),
        Feedback(run_id="run-1", doc_id="LIQ-01", label="useful", user_id="u1"),
    ],
)
def test_round_trip(model):
    restored = type(model).model_validate_json(model.model_dump_json())
    assert restored == model


def test_verdict_without_evidence_rejected():
    for verdict in (Verdict.applicable, Verdict.partial, Verdict.not_applicable):
        with pytest.raises(ValidationError):
            ClauseJudgment(clause_id="C1", verdict=verdict, evidence_quote="  ", confidence=0.8)


def test_uncertain_without_evidence_allowed():
    j = ClauseJudgment(clause_id="C1", verdict=Verdict.uncertain, confidence=0.2)
    assert j.evidence_quote == ""


def test_verdict_requires_clause_id():
    with pytest.raises(ValidationError):
        ClauseJudgment(clause_id="", verdict=Verdict.applicable, evidence_quote="근거", confidence=0.8)


def test_confidence_range():
    with pytest.raises(ValidationError):
        ClauseJudgment(clause_id="C1", verdict=Verdict.uncertain, confidence=1.5)


def test_protected_requires_reason():
    with pytest.raises(ValidationError):
        make_clause(protected=True)
    with pytest.raises(ValidationError):
        make_clause(protected=False, protected_reason="regulatory")
    assert make_clause(protected=True, protected_reason="insurance").protected


def test_playbook_clause_doc_id_mismatch():
    with pytest.raises(ValidationError):
        Playbook(
            doc_id="OTHER", title="t", version="1", year=2020,
            origin_event="x", synthetic=True, clauses=[make_clause()],
        )


def test_severity_range():
    with pytest.raises(ValidationError):
        Event.model_validate({**make_event().model_dump(), "severity": 6})
