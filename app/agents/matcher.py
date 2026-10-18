"""Matcher: 사건 ↔ 대응문서 조항 적합도 판정 (plans.md 5.2).

1. 사건 구조화 (텍스트 → Event). 백테스트는 카드를 재추출해 일치도만 검증하고 카드 값을 쓴다.
2. 후보: 사건 임베딩으로 조항 top-k + protected 조항 항상 포함
3. 판정: 조항 배치별 ClauseJudgment. 근거 인용문은 조항 원문 또는 사건 요약의 실제 문구여야 한다.
   검증 실패 조항만 최대 max_retries회 재질의, 그래도 실패하면 uncertain.
4. fit_score, 공백 채널, 재검색·low_confidence 분기, 순위
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date

from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings, load_config
from app.llm.client import LLMClient, LLMResponseError
from app.retrieval import ClauseIndex, event_query
from app.schemas import Channel, Clause, ClauseJudgment, DocFit, Duration, Event, EventType, MatchResult, Verdict

# ---------- 1. 사건 구조화 ----------


class EventDraft(BaseModel):
    title: str
    summary: str
    type: EventType
    channels: list[Channel]
    regions: list[str]
    sectors: list[str]
    asset_classes: list[str]
    entities: list[str]
    duration: Duration
    severity: int = Field(ge=1, le=5)


STRUCTURE_SYSTEM = """너는 금융 위기 사건을 구조화하는 분석가다. 주어진 텍스트에 근거한 값만 채운다.
- regions: ISO 국가코드(US, KR, CN, RU, UA 등) 또는 EU, EM, GLOBAL
- sectors / asset_classes: 영어 snake_case (예: regional_banks, broker_dealers, govt_bond, high_yield, commercial_paper, money_market)
- severity: 1(경미)~5(시스템 위기)"""


def structure_event(llm: LLMClient, text: str, event_id: str, event_date: date, sources: list[str] | None = None) -> Event:
    draft = llm.generate(f"다음 사건을 구조화하라.\n\n{text}", purpose="structure_event",
                         response_schema=EventDraft, system=STRUCTURE_SYSTEM)
    return Event(id=event_id, date=event_date, sources=sources or [], **draft.model_dump())


def verify_card(llm: LLMClient, card: Event) -> dict:
    """카드의 제목·요약에서 LLM으로 재추출해 카드 구조화값과의 일치도를 계산한다."""
    extracted = structure_event(llm, f"{card.title}\n{card.summary}", card.id, card.date, card.sources)
    a, b = set(card.channels), set(extracted.channels)
    return {
        "type_match": extracted.type == card.type,
        "channel_jaccard": round(len(a & b) / len(a | b), 3) if a | b else 1.0,
        "extracted_type": extracted.type.value,
        "extracted_channels": sorted(c.value for c in extracted.channels),
    }


# ---------- 3. 판정 ----------


class JudgmentDraft(BaseModel):
    clause_id: str
    verdict: Verdict
    mismatch_reasons: list[str]
    evidence_quote: str
    confidence: float


class JudgmentBatch(BaseModel):
    judgments: list[JudgmentDraft]


JUDGE_SYSTEM = """너는 기관투자자의 위기 대응문서를 검토하는 리스크 분석가다.
각 조항은 작성 당시 사건의 전제(premises)에 묶여 있다. 이번 사건과 조항의 전제를 항목별로 대조해 판정하라.
- applicable: 전제가 이번 사건과 맞고 조치를 그대로 실행할 수 있다
- partial: 일부 전제만 맞아 조치를 수정해야 한다
- not_applicable: 핵심 전제가 이번 사건과 다르다
- uncertain: 판단할 정보가 부족하다
규칙:
- evidence_quote: 판정 근거가 되는 문구를 [조항 원문] 또는 [사건 요약]에서 글자 그대로 복사한다. 지어내지 않는다.
- mismatch_reasons: partial/not_applicable이면 어떤 전제가 어떻게 다른지 한국어로 적는다.
- confidence: 0~1
- 모든 조항에 대해 하나씩, clause_id를 그대로 사용한다."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _event_block(event: Event) -> str:
    return json.dumps({
        "제목": event.title, "사건 요약": event.summary, "유형": event.type.value,
        "채널": [c.value for c in event.channels], "지역": event.regions, "업종": event.sectors,
        "자산군": event.asset_classes, "지속기간": event.duration.value, "심각도": event.severity,
    }, ensure_ascii=False, indent=1)


def _clause_block(c: Clause) -> str:
    p = c.premises
    return json.dumps({
        "clause_id": c.clause_id, "조항 원문": c.text,
        "전제": {"사건유형": [t.value for t in p.event_types], "채널": [x.value for x in p.channels],
                 "지역": p.regions, "자산군": p.asset_classes, "지속기간": [d.value for d in p.duration],
                 "조건": p.conditions},
        "조치": c.actions,
    }, ensure_ascii=False)


def validate_draft(draft: JudgmentDraft, clause: Clause, event: Event) -> tuple[ClauseJudgment | None, str | None]:
    """초안을 ClauseJudgment로 검증. 실패 시 (None, 사유)."""
    if draft.verdict != Verdict.uncertain:
        quote = _norm(draft.evidence_quote)
        if not quote:
            return None, "evidence_quote가 비어 있음"
        if quote not in _norm(clause.text) and quote not in _norm(event.summary):
            return None, "evidence_quote가 조항 원문·사건 요약의 실제 문구가 아님"
    try:
        j = ClauseJudgment(
            clause_id=clause.clause_id, verdict=draft.verdict, mismatch_reasons=draft.mismatch_reasons,
            evidence_quote=draft.evidence_quote.strip(), confidence=min(max(draft.confidence, 0.0), 1.0),
        )
    except ValidationError as e:
        return None, str(e.errors()[0]["msg"])
    return j, None


def judge_clauses(llm: LLMClient, event: Event, clauses: list[Clause]) -> list[ClauseJudgment]:
    cfg = load_config()["matcher"]
    out: dict[str, ClauseJudgment] = {}
    for i in range(0, len(clauses), cfg["batch_size"]):
        pending = {c.clause_id: c for c in clauses[i : i + cfg["batch_size"]]}
        feedback: dict[str, str] = {}
        for _ in range(cfg["max_retries"] + 1):
            if not pending:
                break
            prompt = f"[이번 사건]\n{_event_block(event)}\n\n[판정할 조항]\n" + "\n".join(_clause_block(c) for c in pending.values())
            if feedback:
                prompt += "\n\n[이전 응답의 문제 — 수정해서 다시 판정]\n" + "\n".join(f"- {k}: {v}" for k, v in feedback.items())
            try:
                batch = llm.generate(prompt, purpose="judge_clauses", response_schema=JudgmentBatch, system=JUDGE_SYSTEM)
            except LLMResponseError:
                feedback = {cid: "응답 형식 오류" for cid in pending}
                continue
            drafts = {d.clause_id: d for d in batch.judgments}
            feedback = {}
            for cid, clause in list(pending.items()):
                if cid not in drafts:
                    feedback[cid] = "판정 누락"
                    continue
                judgment, err = validate_draft(drafts[cid], clause, event)
                if judgment:
                    out[cid] = judgment
                    del pending[cid]
                else:
                    feedback[cid] = err
        for cid in pending:  # 재시도 소진
            out[cid] = ClauseJudgment(clause_id=cid, verdict=Verdict.uncertain,
                                      mismatch_reasons=[f"검증 실패: {feedback.get(cid, '알 수 없음')}"], confidence=0.0)
    return [out[c.clause_id] for c in clauses]


# ---------- 4. 집계 ----------


def fit_score(judgments: list[ClauseJudgment]) -> float:
    w = load_config()["matcher"]["partial_weight"]
    n = {v: sum(j.verdict == v for j in judgments) for v in Verdict}
    denom = n[Verdict.applicable] + n[Verdict.partial] + n[Verdict.not_applicable]
    return (n[Verdict.applicable] + w * n[Verdict.partial]) / denom if denom else 0.0


def build_doc_fits(judgments: list[ClauseJudgment], clauses: dict[str, Clause]) -> list[DocFit]:
    by_doc: dict[str, list[ClauseJudgment]] = defaultdict(list)
    for j in judgments:
        by_doc[clauses[j.clause_id].doc_id].append(j)
    fits = []
    for doc_id, js in by_doc.items():
        fits.append(DocFit(
            doc_id=doc_id, fit_score=round(fit_score(js), 4),
            n_applicable=sum(j.verdict == Verdict.applicable for j in js),
            n_partial=sum(j.verdict == Verdict.partial for j in js),
            n_not=sum(j.verdict == Verdict.not_applicable for j in js),
            n_uncertain=sum(j.verdict == Verdict.uncertain for j in js),
            judgments=js,
        ))
    return fits


def covers(j: ClauseJudgment, clause: Clause, event: Event) -> bool:
    """공백 규칙 v2 (사전 등록): applicable이거나, partial이면서 조항 전제 사건유형에 이번 사건 유형이 있을 때만 채널을 다룬 것으로 본다."""
    if j.verdict == Verdict.applicable:
        return True
    return j.verdict == Verdict.partial and event.type in clause.premises.event_types


def find_gaps(event: Event, judgments: list[ClauseJudgment], clauses: dict[str, Clause]) -> list[Channel]:
    covered = {ch for j in judgments if covers(j, clauses[j.clause_id], event)
               for ch in clauses[j.clause_id].premises.channels}
    return [ch for ch in event.channels if ch not in covered]


def protected_only(fit: DocFit, clauses: dict[str, Clause]) -> bool:
    """판정된 조항이 모두 protected인 문서 (순위 하단, '필수 확인'으로 별도 표시)."""
    return all(clauses[j.clause_id].protected for j in fit.judgments)


def rank_doc_fits(fits: list[DocFit], learner_enabled: bool | None = None,
                  clauses: dict[str, Clause] | None = None) -> list[DocFit]:
    """LEARNER_ENABLED=false면 fit_score 순. protected 조항만 판정된 문서는 후보에 남기되 하단으로 보낸다.
    학습 층 보정은 P9에서 연결한다."""
    enabled = get_settings().learner_enabled if learner_enabled is None else learner_enabled
    if enabled:
        raise NotImplementedError("Learner 보정은 P9에서 구현")
    tail = (lambda f: protected_only(f, clauses)) if clauses else (lambda f: False)
    return sorted(fits, key=lambda f: (tail(f), -f.fit_score, -f.n_applicable, f.doc_id))


# ---------- 전체 ----------


def _expanded_terms(event: Event) -> str:
    return "확장 검색: " + " ".join([event.type.value] + [c.value for c in event.channels] + event.sectors + event.asset_classes)


def retrieve_candidates(event: Event, index: ClauseIndex, exclude: set[str] | None = None, expanded: bool = False) -> list[Clause]:
    """임베딩 검색 후보. 기본 검색에는 protected 조항을 항상 포함하고, 확장 검색은 top_k×2."""
    cfg = load_config()["matcher"]
    exclude = exclude or set()
    if expanded:
        found = index.search(event_query(event, _expanded_terms(event)), cfg["top_k"] * 2)
    else:
        found = index.search(event_query(event), cfg["top_k"])
        found += [c for c in index.protected() if c.clause_id not in {f.clause_id for f in found}]
    return [c for c in found if c.clause_id not in exclude]


def needs_requery(judgments: list[ClauseJudgment], clauses: dict[str, Clause]) -> bool:
    fits = build_doc_fits(judgments, clauses)
    return max((f.fit_score for f in fits), default=0.0) < load_config()["matcher"]["requery_fit_below"]


def finalize_match(event: Event, judgments: list[ClauseJudgment], clauses: dict[str, Clause]) -> MatchResult:
    confidences = [j.confidence for j in judgments]
    return MatchResult(
        event_id=event.id,
        doc_fits=rank_doc_fits(build_doc_fits(judgments, clauses), clauses=clauses),
        gaps=find_gaps(event, judgments, clauses),
        low_confidence=(sum(confidences) / len(confidences) if confidences else 0.0)
        < load_config()["matcher"]["low_confidence_below"],
    )


def match(event: Event, index: ClauseIndex, llm: LLMClient) -> MatchResult:
    judgments = judge_clauses(llm, event, retrieve_candidates(event, index))
    if needs_requery(judgments, index.clauses):
        # 쿼리 확장 1회 재검색: 새 후보만 추가 판정
        more = retrieve_candidates(event, index, exclude={j.clause_id for j in judgments}, expanded=True)
        judgments += judge_clauses(llm, event, more)
    return finalize_match(event, judgments, index.clauses)
