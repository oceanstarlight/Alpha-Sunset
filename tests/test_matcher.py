from datetime import date

import pytest

from app.agents import matcher
from app.agents.matcher import (
    JudgmentBatch,
    JudgmentDraft,
    build_doc_fits,
    find_gaps,
    fit_score,
    judge_clauses,
    match,
    rank_doc_fits,
    validate_draft,
)
from app.retrieval import ClauseIndex
from app.schemas import Channel, Clause, ClauseJudgment, Duration, Event, EventType, Playbook, Premises, Verdict

EVENT = Event(
    id="svb_2023", title="SVB 파산", date=date(2023, 3, 10), summary="실리콘밸리은행이 폐쇄되었다.",
    type=EventType.banking_stress, channels=[Channel.liquidity, Channel.counterparty, Channel.rates],
    duration=Duration.weeks, severity=4,
)


def clause(cid: str, doc: str, text: str, channels=(), protected=None) -> Clause:
    return Clause(
        clause_id=cid, doc_id=doc, text=text, premises=Premises(channels=list(channels)),
        owner_role="팀", protected=protected is not None, protected_reason=protected,
    )


CLAUSES = [
    clause("A-01", "A", "예치 은행이 폐쇄되면 예금 잔액을 확인한다.", [Channel.liquidity]),
    clause("A-02", "A", "은행 CDS를 모니터링한다.", [Channel.counterparty]),
    clause("B-01", "B", "유가 급등 시 에너지 노출을 줄인다.", [Channel.commodity]),
    clause("R-01", "R", "중대 손실은 감독기관에 보고한다.", [], protected="regulatory"),
]
BY_ID = {c.clause_id: c for c in CLAUSES}


def j(cid: str, verdict: Verdict, conf: float = 0.8) -> ClauseJudgment:
    quote = "" if verdict == Verdict.uncertain else BY_ID[cid].text
    return ClauseJudgment(clause_id=cid, verdict=verdict, evidence_quote=quote, confidence=conf)


class FakeLLM:
    """판정 요청마다 scripted(clause_id → JudgmentDraft 목록) 순서대로 응답한다."""

    embed_model = "fake-embed"

    def __init__(self, scripted: dict[str, list[JudgmentDraft]] | None = None):
        self.scripted = scripted or {}
        self.prompts: list[str] = []

    def generate(self, prompt, purpose, response_schema=None, system=None):
        self.prompts.append(prompt)
        drafts = []
        for cid, queue in self.scripted.items():
            if f'"clause_id": "{cid}"' in prompt and queue:
                drafts.append(queue.pop(0))
        return JudgmentBatch(judgments=drafts)

    def embed(self, texts, purpose):
        # 단어 겹침 기반의 결정적 가짜 임베딩
        vocab = ["은행", "예금", "CDS", "유가", "에너지", "감독기관", "폐쇄"]
        return [[float(w in t) + 0.01 for w in vocab] for t in texts]


def draft(cid: str, verdict: Verdict, quote: str, conf: float = 0.9) -> JudgmentDraft:
    return JudgmentDraft(clause_id=cid, verdict=verdict, mismatch_reasons=[], evidence_quote=quote, confidence=conf)


# ---------- 근거 검증 ----------


def test_quote_must_come_from_clause_or_event():
    c = BY_ID["A-01"]
    ok, _ = validate_draft(draft("A-01", Verdict.applicable, "예금 잔액을 확인한다"), c, EVENT)
    assert ok is not None
    ok, _ = validate_draft(draft("A-01", Verdict.applicable, "실리콘밸리은행이 폐쇄되었다"), c, EVENT)
    assert ok is not None
    bad, err = validate_draft(draft("A-01", Verdict.applicable, "지어낸 근거"), c, EVENT)
    assert bad is None and "실제 문구" in err
    bad, _ = validate_draft(draft("A-01", Verdict.partial, ""), c, EVENT)
    assert bad is None


def test_invalid_judgment_retried_then_uncertain(monkeypatch):
    llm = FakeLLM({"A-01": [draft("A-01", Verdict.applicable, "가짜")] * 3})
    out = judge_clauses(llm, EVENT, [BY_ID["A-01"]])
    assert out[0].verdict == Verdict.uncertain and out[0].confidence == 0.0
    assert len(llm.prompts) == 3  # 최초 + 재시도 2회
    assert "이전 응답의 문제" in llm.prompts[1]


def test_retry_fixes_only_failed_clause():
    llm = FakeLLM({
        "A-01": [draft("A-01", Verdict.applicable, "예금 잔액을 확인한다")],
        "A-02": [draft("A-02", Verdict.partial, "가짜"), draft("A-02", Verdict.partial, "은행 CDS를 모니터링한다")],
    })
    out = judge_clauses(llm, EVENT, [BY_ID["A-01"], BY_ID["A-02"]])
    assert [o.verdict for o in out] == [Verdict.applicable, Verdict.partial]
    assert '"clause_id": "A-01"' not in llm.prompts[1]


def test_no_judgment_without_evidence_ever_returned():
    llm = FakeLLM({c.clause_id: [draft(c.clause_id, Verdict.applicable, "")] * 3 for c in CLAUSES})
    for out in judge_clauses(llm, EVENT, CLAUSES):
        assert out.verdict == Verdict.uncertain or out.evidence_quote


# ---------- 집계 ----------


def test_fit_score_excludes_uncertain():
    js = [j("A-01", Verdict.applicable), j("A-02", Verdict.partial), j("B-01", Verdict.not_applicable), j("R-01", Verdict.uncertain)]
    assert fit_score(js) == pytest.approx((1 + 0.5) / 3)
    assert fit_score([j("R-01", Verdict.uncertain)]) == 0.0


def test_gaps_are_event_channels_not_covered():
    js = [j("A-01", Verdict.applicable), j("A-02", Verdict.not_applicable)]
    assert find_gaps(EVENT, js, BY_ID) == [Channel.counterparty, Channel.rates]


def test_rank_by_fit_score_when_learner_off():
    fits = build_doc_fits([j("A-01", Verdict.partial), j("B-01", Verdict.applicable)], BY_ID)
    assert [f.doc_id for f in rank_doc_fits(fits, learner_enabled=False)] == ["B", "A"]


# ---------- 전체 흐름 ----------


def test_protected_clauses_always_judged(tmp_path, monkeypatch):
    monkeypatch.setitem(matcher.load_config()["matcher"], "top_k", 1)
    playbooks = [Playbook(doc_id=d, title=d, version="1", year=2020, origin_event="x", synthetic=True,
                          clauses=[c for c in CLAUSES if c.doc_id == d]) for d in "ABR"]
    llm = FakeLLM({c.clause_id: [draft(c.clause_id, Verdict.applicable, c.text)] * 5 for c in CLAUSES})
    index = ClauseIndex(playbooks, llm, path=tmp_path / "chroma")
    result = match(EVENT, index, llm)
    judged = {jj.clause_id for f in result.doc_fits for jj in f.judgments}
    assert "R-01" in judged
    assert all(jj.evidence_quote for f in result.doc_fits for jj in f.judgments)


def test_low_fit_triggers_one_requery(tmp_path, monkeypatch):
    monkeypatch.setitem(matcher.load_config()["matcher"], "top_k", 1)
    playbooks = [Playbook(doc_id=d, title=d, version="1", year=2020, origin_event="x", synthetic=True,
                          clauses=[c for c in CLAUSES if c.doc_id == d]) for d in "ABR"]
    llm = FakeLLM({c.clause_id: [draft(c.clause_id, Verdict.not_applicable, c.text)] * 5 for c in CLAUSES})
    index = ClauseIndex(playbooks, llm, path=tmp_path / "chroma")
    result = match(EVENT, index, llm)
    judged = {jj.clause_id for f in result.doc_fits for jj in f.judgments}
    assert len(judged) > 2  # top_k=1 + protected 1 → 재검색으로 후보 추가
