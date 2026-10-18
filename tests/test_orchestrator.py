from types import SimpleNamespace

import pytest
from google.genai import types

from app.agents import orchestrator as orch
from app.agents.exposure import EntityMatches, WhyList
from app.agents.matcher import JudgmentBatch, JudgmentDraft
from app.corpus import load_events, load_portfolio
from app.retrieval import ClauseIndex
from app.schemas import Clause, Playbook, Premises, Verdict

SVB = next(e for e in load_events() if e.id == "svb_2023")

CLAUSES = [
    Clause(clause_id="A-01", doc_id="A", text="예치 은행이 폐쇄되면 예금 잔액을 확인한다.", premises=Premises(),
           actions=["예금 잔액 확인"], owner_role="자금운용팀"),
    Clause(clause_id="A-02", doc_id="A", text="은행 CDS를 모니터링한다.", premises=Premises(),
           actions=["예금 잔액 확인", "CDS 모니터링"], owner_role="자금운용팀"),
    Clause(clause_id="R-01", doc_id="R", text="중대 손실은 감독기관에 보고한다.", premises=Premises(),
           actions=["감독기관 보고"], owner_role="준법감시팀", protected=True, protected_reason="regulatory"),
]


class FakeLLM:
    embed_model = "fake-embed"

    def __init__(self, verdict=Verdict.applicable, script=None):
        self.verdict = verdict
        self.script = list(script or [])  # chat 턴마다 호출할 도구 이름 목록
        self.chat_calls = 0

    def generate(self, prompt, purpose, response_schema=None, system=None):
        if response_schema is JudgmentBatch:
            drafts = [JudgmentDraft(clause_id=c.clause_id, verdict=self.verdict, mismatch_reasons=[],
                                    evidence_quote=c.text, confidence=0.9)
                      for c in CLAUSES if f'"clause_id": "{c.clause_id}"' in prompt]
            return JudgmentBatch(judgments=drafts)
        if response_schema is EntityMatches:
            return EntityMatches(matches=[])
        if response_schema is WhyList:
            return WhyList(whys=["이유"] * prompt.count('"경로"'))
        return response_schema(actions=prompt.split("\n"))

    def embed(self, texts, purpose):
        vocab = ["은행", "예금", "CDS", "감독기관"]
        return [[float(w in t) + 0.01 for w in vocab] for t in texts]

    def chat(self, contents, purpose, tools, system=None):
        self.chat_calls += 1
        names = self.script.pop(0) if self.script else []
        return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=n, args={})) for n in names])


@pytest.fixture
def ctx_factory(tmp_path):
    def make(llm):
        playbooks = [Playbook(doc_id=d, title=d, version="1", year=2020, origin_event="x", synthetic=True,
                              clauses=[c for c in CLAUSES if c.doc_id == d]) for d in "AR"]
        return orch.new_context(mode="sandbox", as_of=SVB.date, events=[SVB], portfolio=load_portfolio(),
                                index=ClauseIndex(playbooks, llm, path=tmp_path / "chroma"), llm=llm, panel={})
    return make


def test_build_briefing_refused_before_required_tools(ctx_factory):
    ctx = ctx_factory(FakeLLM())
    out = orch.execute_tool(ctx, "build_briefing")
    assert "거부" in out["error"] and ctx.briefing is None
    trace = orch.get_trace(ctx.trace_id)
    assert trace[0]["tool"] == "build_briefing" and "거부" in trace[0]["output_summary"]


def test_agent_loop_runs_tools_in_llm_order(ctx_factory):
    script = [["get_market_signals"], ["search_events"], ["retrieve_clauses"], ["judge_clauses"],
              ["compute_exposure", "get_priority"], ["build_briefing"]]
    llm = FakeLLM(script=script)
    ctx = ctx_factory(llm)
    b = orch.orchestrate(ctx, "task")
    assert [r["tool"] for r in orch.get_trace(ctx.trace_id)] == [n for turn in script for n in turn]
    assert b.event.id == "svb_2023" and b.trace_id == ctx.trace_id
    assert orch.get_briefing(b.run_id) == b
    assert b.exposure_top and "R-01" in {j.clause_id for f in b.match.doc_fits for j in f.judgments}


def test_premature_briefing_then_recovery(ctx_factory):
    script = [["get_market_signals", "search_events", "build_briefing"]]  # 판정·노출 없이 브리핑 시도
    ctx = ctx_factory(FakeLLM(script=script))
    b = orch.orchestrate(ctx, "task")
    tools = [r["tool"] for r in orch.get_trace(ctx.trace_id)]
    assert tools[:3] == ["get_market_signals", "search_events", "build_briefing"]
    assert "fallback" in tools
    assert tools.index("judge_clauses") < len(tools) - 1 and tools[-1] == "build_briefing"
    assert b is not None


def test_fallback_when_llm_stops_without_calls(ctx_factory):
    ctx = ctx_factory(FakeLLM(script=[]))
    b = orch.orchestrate(ctx, "task")
    tools = [r["tool"] for r in orch.get_trace(ctx.trace_id)]
    assert tools[0] == "fallback" and tools[1:] == orch.TOOL_ORDER
    assert b.alert_level.value in {"ALERT", "WATCH", "NONE"}


def test_low_fit_triggers_clause_requery_once(ctx_factory, monkeypatch):
    from app.agents import matcher

    monkeypatch.setitem(matcher.load_config()["matcher"], "top_k", 1)
    ctx = ctx_factory(FakeLLM(verdict=Verdict.not_applicable))
    for name in ["get_market_signals", "search_events", "retrieve_clauses"]:
        orch.execute_tool(ctx, name)
    before = len(ctx.candidates)
    out = orch.execute_tool(ctx, "judge_clauses")
    assert out["requeried"] is True and len(ctx.candidates) > before


def test_aggregate_actions_merges_duplicates(ctx_factory):
    ctx = ctx_factory(FakeLLM())
    for name in ["get_market_signals", "search_events", "retrieve_clauses", "judge_clauses"]:
        orch.execute_tool(ctx, name)
    actions = orch.aggregate_actions(ctx.match, ctx.index.clauses)
    dup = [a for a in actions if "예금 잔액 확인" in a]
    assert len(dup) == 1 and "A-01" in dup[0] and "A-02" in dup[0]
    assert any(a.startswith("[준법감시팀]") for a in actions)


def test_gfc_briefing_without_exposure(tmp_path):
    gfc = next(e for e in load_events() if e.id == "gfc_2008")
    llm = FakeLLM()
    playbooks = [Playbook(doc_id="A", title="A", version="1", year=2020, origin_event="x", synthetic=True, clauses=CLAUSES[:2])]
    ctx = orch.new_context(mode="sandbox", as_of=gfc.date, events=[gfc], portfolio=load_portfolio(),
                           index=ClauseIndex(playbooks, llm, path=tmp_path / "c"), llm=llm, panel={})
    b = orch.orchestrate(ctx, "task")
    assert b.exposure_top == [] and "노출 분석 불가" in b.exposure_note


def test_uploaded_portfolio_and_holdings_flow_into_briefing(tmp_path):
    """업로드 포트폴리오로 노출 분석, 보유 종목명은 규칙으로만 사건 기관과 대조, 가정 분석 고지."""
    from pathlib import Path

    from app.ingest.pipeline import ingest
    from app.ingest.transform import to_portfolio

    res, _ = ingest(Path(__file__).resolve().parent.parent / "data" / "ingest" / "samples" / "broker_balance.xlsx",
                    use_preset=False)
    pf = to_portfolio(res.holdings, institution="업로드테스트")
    holdings = [{"name": "SILICON VALLEY BANK", "weight": 0.01, "country": "US", "sector": "Financials", "source_row": 7},
                {"name": "Federal Reserve Bank", "weight": 0.02}]  # 공공기관은 매칭하지 않는다
    llm = FakeLLM()
    playbooks = [Playbook(doc_id="A", title="A", version="1", year=2020, origin_event="x", synthetic=True, clauses=CLAUSES[:2])]
    svb = SVB.as_of_view()
    ctx = orch.new_context(mode="sandbox", as_of=svb.date, events=[svb], portfolio=pf,
                           index=ClauseIndex(playbooks, llm, path=tmp_path / "c"), llm=llm, panel={}, holdings=holdings,
                           portfolio_note="업로드 가정 분석")
    b = orch.orchestrate(ctx, "task")
    assert all(p.nodes[1].startswith("U-") for p in b.exposure_top)  # 업로드 노드로 노출 계산
    assert [p.nodes[2] for p in b.exposure_entities if p.nodes[1] == "업로드 직접 보유"] == ["SILICON VALLEY BANK"]
    assert b.exposure_note.startswith("업로드 가정 분석")
