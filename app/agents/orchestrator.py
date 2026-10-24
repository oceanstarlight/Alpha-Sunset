"""Orchestrator: Gemini 함수 호출 루프로 도구를 조합해 Briefing을 만든다 (plans.md 5.5).

- LLM은 도구 호출 순서만 정한다. 도구 입력·상태는 코드가 들고 있다 (사건 데이터 조작 불가).
- 하드 제약(코드 강제): build_briefing은 judge_clauses와 compute_exposure 실행 후에만 허용.
  분기 규칙: fit_score < 0.4면 확장 재검색 1회(judge_clauses 안에서), 불확실 경로 비율 > 0.5면 보유내역 재조회 1회.
- 모든 도구 호출의 입력·출력 요약을 traces 테이블에 저장한다.
- LLM이 max_steps 안에 브리핑을 끝내지 못하면 남은 단계를 코드가 정해진 순서로 마저 실행한다.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel

from app.agents import exposure as exposure_agent
from app.agents import matcher as matcher_agent
from app.agents import sentinel as sentinel_agent
from app.config import get_settings, load_config
from app.db import DbMode, connect
from app.llm.client import LLMClient, LLMResponseError, LLMUnavailableError
from app.retrieval import ClauseIndex
from app.schemas import (
    AlertLevel,
    Briefing,
    Clause,
    ClauseJudgment,
    Event,
    MatchResult,
    Portfolio,
    Verdict,
)

TOOL_ORDER = ["get_market_signals", "search_events", "retrieve_clauses", "judge_clauses",
              "compute_exposure", "get_priority", "build_briefing"]
REQUIRED_BEFORE_BRIEFING = ("judge_clauses", "compute_exposure")


class ToolError(RuntimeError):
    """하드 제약 위반 등으로 도구 실행을 거부."""


@dataclass
class RunContext:
    run_id: str
    trace_id: str
    mode: DbMode
    as_of: date
    events: list[Event]  # as_of 시점에 알려진 사건 후보 (백테스트는 카드)
    portfolio: Portfolio
    index: ClauseIndex
    llm: LLMClient
    panel: dict
    live: bool = False
    holdings: list[dict] | None = None  # 업로드 보유 종목 (사건 기관 동일 이름 확인용)
    portfolio_note: str = ""  # 예: 업로드 포트폴리오 가정 분석
    executed: list[str] = field(default_factory=list)
    step: int = 0
    # 도구 결과
    market: sentinel_agent.MarketSignal | None = None
    flow: sentinel_agent.FlowSignal | None = None
    news: sentinel_agent.NewsSignal | None = None
    event: Event | None = None
    candidates: list[Clause] = field(default_factory=list)
    judgments: list[ClauseJudgment] = field(default_factory=list)
    requeried_clauses: bool = False
    match: MatchResult | None = None
    exposure: exposure_agent.ExposureReport | None = None
    exposure_note: str = ""
    requeried_exposure: bool = False
    priority: list[dict] = field(default_factory=list)
    briefing: Briefing | None = None


# ---------- trace ----------


def _summary(obj: Any, limit: int = 1500) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def record_trace(ctx: RunContext, tool: str, args: dict, output: Any) -> None:
    ctx.step += 1
    conn = connect(ctx.mode)
    with conn:
        conn.execute(
            "INSERT INTO traces (trace_id, step, tool, input_summary, output_summary, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.trace_id, ctx.step, tool, _summary(args), _summary(output), datetime.now(timezone.utc).isoformat()),
        )
    conn.close()


# ---------- 도구 ----------


def tool_get_market_signals(ctx: RunContext, **_) -> dict:
    view = sentinel_agent.AsOfPanel(ctx.panel, as_of=None if ctx.live else ctx.as_of)
    ctx.market = sentinel_agent.market_signal(view, ctx.as_of)
    ctx.flow = sentinel_agent.flow_signal(view, ctx.as_of) if sentinel_agent.flow_enabled() else None
    ctx.news = sentinel_agent.card_news_signal(ctx.events, ctx.as_of)
    level = sentinel_agent.grade(ctx.market, ctx.news, ctx.flow)
    return {"as_of": ctx.as_of.isoformat(), "level": level.value, "market_active": ctx.market.active,
            "triggered_series": ctx.market.triggered,
            "zscores": {k: round(v, 2) for k, v in ctx.market.zscores.items()},
            "flow_active": bool(ctx.flow and ctx.flow.active), "flow_triggered": ctx.flow.triggered if ctx.flow else [],
            "news_clusters": [c.key for c in ctx.news.clusters]}


def tool_search_events(ctx: RunContext, **_) -> dict:
    """as_of 시점에 보도된 사건 후보. 후보가 하나면 자동 선택."""
    news = ctx.news or sentinel_agent.card_news_signal(ctx.events, ctx.as_of)
    known = [e for e in ctx.events if e.id in {c.key for c in news.clusters}]
    if known:
        ctx.event = known[0]
    return {"events": [{"id": e.id, "title": e.title, "type": e.type.value, "date": e.date.isoformat()} for e in known],
            "selected": ctx.event.id if ctx.event else None}


def _require_event(ctx: RunContext) -> Event:
    if ctx.event is None:
        raise ToolError("사건이 선택되지 않았다. search_events를 먼저 호출하라.")
    return ctx.event


def tool_retrieve_clauses(ctx: RunContext, **_) -> dict:
    event = _require_event(ctx)
    ctx.candidates = matcher_agent.retrieve_candidates(event, ctx.index)
    return {"n_candidates": len(ctx.candidates), "n_protected": sum(c.protected for c in ctx.candidates),
            "docs": sorted({c.doc_id for c in ctx.candidates})}


def tool_judge_clauses(ctx: RunContext, **_) -> dict:
    event = _require_event(ctx)
    if not ctx.candidates:
        raise ToolError("후보 조항이 없다. retrieve_clauses를 먼저 호출하라.")
    ctx.judgments = matcher_agent.judge_clauses(ctx.llm, event, ctx.candidates)
    if not ctx.requeried_clauses and matcher_agent.needs_requery(ctx.judgments, ctx.index.clauses):
        # 하드 규칙 5.2-6: 최고 fit_score < 0.4 → 확장 재검색 1회
        ctx.requeried_clauses = True
        more = matcher_agent.retrieve_candidates(event, ctx.index, exclude={j.clause_id for j in ctx.judgments}, expanded=True)
        ctx.candidates += more
        ctx.judgments += matcher_agent.judge_clauses(ctx.llm, event, more)
    ctx.match = matcher_agent.finalize_match(event, ctx.judgments, ctx.index.clauses)
    return {"requeried": ctx.requeried_clauses, "low_confidence": ctx.match.low_confidence,
            "gaps": [g.value for g in ctx.match.gaps],
            "top_docs": [{"doc_id": f.doc_id, "fit_score": f.fit_score} for f in ctx.match.doc_fits[:5]],
            "verdicts": {v.value: sum(j.verdict == v for j in ctx.judgments) for v in Verdict}}


def tool_compute_exposure(ctx: RunContext, **_) -> dict:
    event = _require_event(ctx)
    try:
        rep = exposure_agent.compute_exposure(event, ctx.portfolio, ctx.llm, live=ctx.live)
    except exposure_agent.ExposureUnavailable as e:
        ctx.exposure, ctx.exposure_note = None, f"노출 분석 불가: {e}"
        return {"available": False, "note": ctx.exposure_note}
    if rep.needs_requery and not ctx.requeried_exposure:
        # 하드 규칙 5.3: 불확실 경로 비율 > 0.5 → 보유내역 재조회 후 재계산 1회
        ctx.requeried_exposure = True
        if ctx.live:
            rep = exposure_agent.compute_exposure(event, ctx.portfolio, ctx.llm, live=True)
        else:
            ctx.exposure_note = "불확실 경로 비율이 높지만 백테스트 시점에 추가 공개된 보유내역이 없다"
    if ctx.holdings:
        rep.entity_paths = exposure_agent.holding_entity_paths(event, ctx.holdings) + rep.entity_paths
    ctx.exposure = rep
    return {"available": True, "uncertain_ratio": rep.uncertain_ratio, "requeried": ctx.requeried_exposure,
            "top_paths": [" → ".join(p.nodes[1:]) for p in rep.paths[:5]],
            "entity_matches": rep.entity_matches}


def tool_get_priority(ctx: RunContext, **_) -> dict:
    """문서 우선순위 (Learner). 점수는 항상 계산해 보여주고, ON일 때만 순위에 반영한다."""
    from app.agents import learner

    if ctx.match is None or ctx.event is None:
        raise ToolError("judge_clauses를 먼저 호출하라.")
    mode = "live" if ctx.mode == "live" else "backtest"
    protected = {c.doc_id for c in ctx.index.clauses.values() if c.protected}
    pri = learner.compute_priority([f.doc_id for f in ctx.match.doc_fits], ctx.event.type.value, ctx.as_of, mode, protected)
    enabled = learner.is_enabled()
    if enabled:
        tail = {f.doc_id for f in ctx.match.doc_fits if matcher_agent.protected_only(f, ctx.index.clauses)}
        ctx.match = ctx.match.model_copy(update={"doc_fits": learner.rerank(ctx.match.doc_fits, pri, tail)})
    ctx.priority = [{"doc_id": f.doc_id, "fit_score": f.fit_score, "priority": pri[f.doc_id].priority} for f in ctx.match.doc_fits]
    return {"learner_enabled": enabled, "ranking": ctx.priority[:5]}


class CleanedActions(BaseModel):
    actions: list[str]


ACTIONS_SYSTEM = """기관투자자 위기 대응 확인 항목을 다듬는다. 각 항목의 의미·담당·조항 번호는 그대로 두고 문장만 자연스럽게 고친다.
입력과 같은 순서, 같은 개수로 반환한다. 새 항목을 추가하거나 합치지 않는다."""


def aggregate_actions(match: MatchResult, clauses: dict[str, Clause]) -> list[str]:
    """applicable/partial 조항의 조치를 담당 역할별로 모은다 (중복 조치는 조항 번호만 합친다)."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for fit in match.doc_fits:
        for j in fit.judgments:
            if j.verdict not in (Verdict.applicable, Verdict.partial):
                continue
            c = clauses[j.clause_id]
            for action in c.actions:
                grouped.setdefault((c.owner_role, action), []).append(c.clause_id + ("" if j.verdict == Verdict.applicable else "·부분"))
    return [f"[{role}] {action} ({', '.join(ids)})" for (role, action), ids in grouped.items()]


def clean_actions(llm: LLMClient, actions: list[str]) -> list[str]:
    if not actions:
        return actions
    try:
        res = llm.generate("\n".join(actions), purpose="clean_actions", response_schema=CleanedActions, system=ACTIONS_SYSTEM)
    except (LLMResponseError, LLMUnavailableError):
        return actions
    return res.actions if len(res.actions) == len(actions) else actions


def tool_build_briefing(ctx: RunContext, **_) -> dict:
    missing = [t for t in REQUIRED_BEFORE_BRIEFING if t not in ctx.executed]
    if missing:
        raise ToolError(f"build_briefing 거부: {', '.join(missing)} 미실행")
    event = _require_event(ctx)
    level = sentinel_agent.grade(ctx.market, ctx.news, ctx.flow) if ctx.market and ctx.news else AlertLevel.NONE
    actions = clean_actions(ctx.llm, aggregate_actions(ctx.match, ctx.index.clauses))
    evidence = [j.clause_id for f in ctx.match.doc_fits for j in f.judgments if j.evidence_quote] + event.sources
    ctx.briefing = Briefing(
        run_id=ctx.run_id, event=event, alert_level=level, match=ctx.match,
        exposure_top=ctx.exposure.paths if ctx.exposure else [],
        exposure_entities=ctx.exposure.entity_paths if ctx.exposure else [],
        exposure_core=ctx.exposure.core_paths if ctx.exposure else [],
        exposure_note=ctx.exposure_note, actions_to_check=actions, evidence_refs=evidence, trace_id=ctx.trace_id,
    )
    now = datetime.now(timezone.utc).isoformat()
    shadow_mode = "live" if ctx.mode == "live" else "backtest"
    conn = connect(ctx.mode)
    with conn:
        conn.execute("INSERT OR REPLACE INTO briefings (run_id, event_id, payload, ts) VALUES (?, ?, ?, ?)",
                     (ctx.run_id, event.id, ctx.briefing.model_dump_json(), now))
        # 학습 층 입력: 플래그와 무관하게 항상 기록 (5.4)
        conn.executemany(
            "INSERT INTO shadow_log (event_id, doc_id, event_type, cited, rank, feedback, mode, ts) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
            [(event.id, f.doc_id, event.type.value, int(f.n_applicable + f.n_partial > 0), rank, shadow_mode, now)
             for rank, f in enumerate(ctx.match.doc_fits, start=1)],
        )
    conn.close()
    return {"run_id": ctx.run_id, "alert_level": level.value, "n_actions": len(actions)}


TOOLS: dict[str, tuple[Callable[..., dict], str]] = {
    "get_market_signals": (tool_get_market_signals, "기준일의 시장 신호(A)와 사건 신호(B), 경보 등급을 조회한다."),
    "search_events": (tool_search_events, "기준일에 보도된 사건 후보를 찾고 분석 대상 사건을 선택한다."),
    "retrieve_clauses": (tool_retrieve_clauses, "선택된 사건과 관련된 대응문서 조항 후보를 검색한다 (protected 조항 포함)."),
    "judge_clauses": (tool_judge_clauses, "후보 조항별 적용/부분적용/부적용을 판정하고 문서 적합도와 공백을 계산한다."),
    "compute_exposure": (tool_compute_exposure, "가상 포트폴리오에서 사건과 연관된 보유 경로와 위험도를 계산한다."),
    "get_priority": (tool_get_priority, "문서 우선순위를 조회한다."),
    "build_briefing": (tool_build_briefing, "최종 브리핑을 만든다. judge_clauses와 compute_exposure 실행 후에만 가능하다."),
}


def execute_tool(ctx: RunContext, name: str, args: dict | None = None) -> dict:
    args = args or {}
    if name not in TOOLS:
        out = {"error": f"알 수 없는 도구: {name}"}
    else:
        try:
            out = TOOLS[name][0](ctx, **args)
            ctx.executed.append(name)
        except ToolError as e:
            out = {"error": str(e)}
    record_trace(ctx, name, args, out)
    return out


# ---------- 루프 ----------

ORCH_SYSTEM = """너는 기관투자자의 위기 대응 에이전트다. 도구를 호출해 사건 브리핑을 만든다.
권장 순서: get_market_signals → search_events → retrieve_clauses → judge_clauses → compute_exposure → get_priority → build_briefing.
build_briefing은 judge_clauses와 compute_exposure를 실행한 뒤에만 호출할 수 있다.
도구가 error를 반환하면 그 내용에 맞게 필요한 도구를 먼저 호출한다. build_briefing이 성공하면 종료한다."""


def _tool_declarations() -> list[Any]:
    from google.genai import types

    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=name, description=desc, parameters_json_schema={"type": "object", "properties": {}})
        for name, (_, desc) in TOOLS.items()
    ])]


def run_agent_loop(ctx: RunContext, task: str) -> None:
    from google.genai import types

    max_steps = load_config()["orchestrator"]["max_steps"]
    tools = _tool_declarations()
    contents = [types.Content(role="user", parts=[types.Part(text=task)])]
    for _ in range(max_steps):
        reply = ctx.llm.chat(contents, purpose="orchestrator", tools=tools, system=ORCH_SYSTEM)
        calls = [p.function_call for p in (reply.parts or []) if p.function_call]
        if not calls:
            break
        contents.append(reply)
        responses = []
        for call in calls:
            out = execute_tool(ctx, call.name, dict(call.args or {}))
            responses.append(types.Part.from_function_response(name=call.name, response={"result": out}))
        contents.append(types.Content(role="user", parts=responses))
        if ctx.briefing is not None:
            return


def complete_deterministically(ctx: RunContext) -> None:
    """LLM 루프가 브리핑을 끝내지 못했을 때 남은 단계를 정해진 순서로 실행한다."""
    record_trace(ctx, "fallback", {}, {"reason": "LLM 루프가 build_briefing까지 도달하지 못함", "executed": ctx.executed})
    for name in TOOL_ORDER:
        if ctx.briefing is not None:
            return
        if name == "build_briefing" or name not in ctx.executed:
            out = execute_tool(ctx, name)
            if "error" in out and name != "build_briefing":
                raise RuntimeError(f"{name} 실패: {out['error']}")


def new_context(**kwargs) -> RunContext:
    return RunContext(run_id=f"run-{uuid.uuid4().hex[:12]}", trace_id=f"trace-{uuid.uuid4().hex[:12]}", **kwargs)


def orchestrate(ctx: RunContext, task: str) -> Briefing:
    run_agent_loop(ctx, task)
    if ctx.briefing is None:
        complete_deterministically(ctx)
    if ctx.briefing is None:
        raise RuntimeError("브리핑 생성 실패")
    if ctx.portfolio_note:
        note = " · ".join(x for x in (ctx.portfolio_note, ctx.briefing.exposure_note) if x)
        ctx.briefing = ctx.briefing.model_copy(update={"exposure_note": note})
    return ctx.briefing


# ---------- 진입점 ----------


def _index(playbooks: list | None, llm: LLMClient) -> tuple[ClauseIndex, str]:
    """업로드 문서는 별도 폴더에 색인 (기본 색인을 다시 만들지 않게)."""
    from app.corpus import load_playbooks

    if not playbooks:
        return ClauseIndex(load_playbooks(), llm), ""
    import hashlib

    from app.config import ROOT_DIR

    key = hashlib.sha1("|".join(sorted(c.clause_id + c.text for p in playbooks for c in p.clauses)).encode()).hexdigest()[:12]
    note = f"대응 문서: 업로드 {len(playbooks)}개({sum(len(p.clauses) for p in playbooks)}조항) 기준"
    return ClauseIndex(playbooks, llm, path=ROOT_DIR / "data" / "chroma_uploaded" / f"{llm.provider}_{key}"), note


def run_replay(event_id: str, llm: LLMClient | None = None, portfolio: Portfolio | None = None,
               holdings: list[dict] | None = None, playbooks: list | None = None) -> Briefing:
    """백테스트 사건 재생 → Briefing (sandbox DB). 기준일 = 사건 카드 date."""
    from app.corpus import load_events, load_playbooks, load_portfolio
    from app.data.fred import load_panel

    events = load_events()
    target = next((e for e in events if e.id == event_id), None)
    if target is None:
        raise ValueError(f"알 수 없는 사건: {event_id}")
    target = target.as_of_view()  # 사건일 당일까지 알려진 사실만 입력 (사후 정보 누수 방지)
    llm = llm or LLMClient(db_mode="sandbox")
    panel = load_panel(sentinel_agent.panel_series_ids())
    note = (f"업로드 포트폴리오 '{portfolio.institution}'(현재 보유)를 과거 사건에 적용한 가정 분석 — 사건 당시 보유와 다르다"
            if portfolio is not None else "")
    index, doc_note = _index(playbooks, llm)
    note = " · ".join(x for x in (note, doc_note) if x)
    ctx = new_context(mode="sandbox", as_of=target.date, events=[target], portfolio=portfolio or load_portfolio(),
                      index=index, llm=llm, panel=panel, holdings=holdings, portfolio_note=note)
    return orchestrate(ctx, f"{target.date.isoformat()} 기준으로 사건을 탐지하고 대응문서 적합도와 노출을 분석해 브리핑을 만들어라.")


def run_live_briefing(event: Event, panel: dict, llm: LLMClient | None = None, portfolio: Portfolio | None = None,
                      holdings: list[dict] | None = None, playbooks: list | None = None) -> Briefing:
    """라이브 사건(뉴스 군집을 구조화한 Event)으로 브리핑 생성 (live DB, 최신 보유내역)."""
    from app.corpus import load_playbooks, load_portfolio

    llm = llm or LLMClient(db_mode="live")
    note = f"업로드 포트폴리오 '{portfolio.institution}' 기준" if portfolio is not None else ""
    index, doc_note = _index(playbooks, llm)
    note = " · ".join(x for x in (note, doc_note) if x)
    ctx = new_context(mode="live", as_of=event.date, events=[event], portfolio=portfolio or load_portfolio(),
                      index=index, llm=llm, panel=panel, live=True, holdings=holdings, portfolio_note=note)
    return orchestrate(ctx, f"{event.date.isoformat()} 현재 탐지된 사건의 대응문서 적합도와 노출을 분석해 브리핑을 만들어라.")


def get_trace(trace_id: str, mode: DbMode = "sandbox") -> list[dict]:
    conn = connect(mode)
    rows = [dict(r) for r in conn.execute("SELECT step, tool, input_summary, output_summary, ts FROM traces WHERE trace_id = ? ORDER BY step", (trace_id,))]
    conn.close()
    return rows


def get_briefing(run_id: str, mode: DbMode = "sandbox") -> Briefing | None:
    conn = connect(mode)
    row = conn.execute("SELECT payload FROM briefings WHERE run_id = ?", (run_id,)).fetchone()
    conn.close()
    return Briefing.model_validate_json(row["payload"]) if row else None
