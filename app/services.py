"""UI(Streamlit)가 직접 호출하는 서비스 함수 모음 (plans.md 6장)."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app import audit
from app.agents import orchestrator, sentinel
from app.agents.matcher import structure_event
from app.config import ROOT_DIR, get_settings, load_config
from app.data.fred import load_panel
from app.db import DbMode, connect
from app.llm.client import LLMClient
from app.schemas import Briefing, Event, Feedback

BACKTEST_DIR = ROOT_DIR / "data" / "backtest"
LIVE_SIGNALS_PATH = ROOT_DIR / "data" / "live" / "signals_latest.json"
SIGNAL_TTL_SEC = 3600

_signal_cache: dict[str, Any] = {}


def market_panel(refresh: bool = False) -> dict:
    return load_panel(sentinel.panel_series_ids(), refresh=refresh)


GLOBAL_NEWS_HISTORY = ROOT_DIR / "data" / "live" / "global_news_history.jsonl"


def read_global_history() -> list[dict]:
    if not GLOBAL_NEWS_HISTORY.exists():
        return []
    return [json.loads(x) for x in GLOBAL_NEWS_HISTORY.read_text(encoding="utf-8").splitlines() if x.strip()]


def _money_alert_now(panel: dict, as_of) -> bool:
    """1단계 자금 이상 알림 — 백테스트와 같은 지속성 규칙 (끝나는 5영업일 중 min_active일 이상 A∨C)."""
    from app.backtest import money_alert_days

    import pandas as pd

    return bool(money_alert_days(panel, pd.DatetimeIndex([pd.Timestamp(as_of)])).iloc[0])


def compute_signals(rss: Any = None, fred_cache_dir: Path | None = None, now: datetime | None = None) -> dict:
    """최신 시그널 A/B/C와 등급. B는 Google 뉴스 RSS 주제별 기사 수 (기준선은 수집기 누적 이력)."""
    try:
        panel = load_panel(sentinel.panel_series_ids(), **({"cache_dir": fred_cache_dir} if fred_cache_dir else {}),
                           refresh=True)
        fred_error = None
    except Exception as e:  # 네트워크 실패 시 커밋된 캐시로 계산
        panel, fred_error = market_panel(refresh=False), str(e)
    today = date.today()
    last_obs = max(s.index[-1] for s in panel.values()).date()
    market = sentinel.market_signal(sentinel.AsOfPanel(panel), last_obs)
    flow = sentinel.flow_signal(sentinel.AsOfPanel(panel), today) if sentinel.flow_enabled() else None
    if rss is None:
        from app.data.korea import GoogleNewsRss

        rss = GoogleNewsRss(http=__import__("httpx").Client(timeout=10, follow_redirects=True), lang="en-US", region="US")
    now = now or datetime.now(timezone.utc)
    articles, legacy, fetch_errors = sentinel.fetch_rss_topics(rss, now)
    news, rows, obs = sentinel.rss_news_signal(articles, read_global_history(), now, fetch_errors, legacy)
    level = sentinel.grade(market, news, flow)
    chain = sentinel.explain(sentinel.SentinelResult(as_of=last_obs, level=level, market=market, news=news, flow=flow))
    return {
        "fetched_at": time.time(),
        "collected_at": now.isoformat(timespec="seconds"),
        "as_of": last_obs.isoformat(),
        "level": level.value,
        "chain": chain,  # 원인-근거-결과
        # 1단계: 자금·시장 이상 알림 (사건 확정 전), 2단계: 사건 확정 시 대응안(ALERT)
        "money_alert": _money_alert_now(panel, last_obs),
        "market": {"active": market.active, "triggered": market.triggered,
                   "zscores": {k: round(v, 2) for k, v in market.zscores.items()}},
        "flow": {"active": flow.active, "triggered": flow.triggered,
                 "zscores": {k: round(v, 2) for k, v in flow.zscores.items()}} if flow else None,
        "news": {"active": news.active, "status": news.status, "n_queries": news.n_queries, "errors": news.errors,
                 "clusters": [c.__dict__ for c in news.clusters], "observations": obs, "source": "Google 뉴스 RSS"},
        "news_rows": rows,  # 수집기가 기준선 이력에 덧붙이는 이번 관측
        "fred_error": fred_error,
        "panel": panel,
    }


def load_collected_signals(with_panel: bool = True) -> dict | None:
    """GitHub Actions 일일 수집기(scripts/collect_signals.py)가 커밋한 최신 시그널."""
    if not LIVE_SIGNALS_PATH.exists():
        return None
    data = json.loads(LIVE_SIGNALS_PATH.read_text(encoding="utf-8"))
    data["source"] = "collector"
    if with_panel:
        data["panel"] = market_panel()  # 라이브 브리핑용 (커밋된 FRED 캐시)
    return data


def load_local_signals() -> dict | None:
    """로컬(대한민국) 감시 결과 (scripts/monitor_kr.py, GitHub Actions)."""
    path = LIVE_SIGNALS_PATH.parent / "kr_latest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def list_local_reports() -> list[Path]:
    return sorted((LIVE_SIGNALS_PATH.parent / "reports").glob("*.md"), reverse=True)


def get_signals(refresh: bool = False, rss: Any = None) -> dict:
    """refresh=False면 일일 수집 결과를 쓰고, 없거나 refresh=True면 직접 조회한다 (1시간 캐시)."""
    if not refresh:
        collected = load_collected_signals()
        if collected:
            return collected
    cached = _signal_cache.get("signals")
    if cached and not refresh and time.time() - cached["fetched_at"] < SIGNAL_TTL_SEC:
        return cached
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:  # 커밋된 data/fred(백테스트 재현용)를 덮어쓰지 않는다
        result = compute_signals(rss, fred_cache_dir=Path(tmp))
    result["source"] = "live"
    _signal_cache["signals"] = result
    return result


def run_live(signals: dict | None = None, portfolio=None, holdings: list[dict] | None = None,
             playbooks: list | None = None, audit_source: str = "app") -> Briefing | None:
    """현재 사건 탐지 → Briefing. 사건 신호(B)가 없으면 None."""
    signals = signals or get_signals()
    clusters = signals["news"]["clusters"]
    if not clusters:
        return None
    top = clusters[0]
    llm = LLMClient(db_mode="live")
    text = f"{top['label']}\n(뉴스 군집: {top['event_type']}, 기사 {top['n_articles']}건, 출처 {top['n_sources']}곳)"
    event = structure_event(llm, text, f"live_{date.today():%Y%m%d}_{top['event_type']}", date.today())
    b = orchestrator.run_live_briefing(event, signals["panel"], llm, portfolio=portfolio, holdings=holdings,
                                       playbooks=playbooks)
    audit_briefing(b, "live", llm.provider, portfolio, playbooks, source=audit_source)
    return b


def scenario_event(event_type: str, description: str, title: str = "", channels: list[str] | None = None,
                   regions: list[str] | None = None, entities: list[str] | None = None, severity: int = 3,
                   duration: str = "weeks", on: date | None = None) -> Event:
    """시나리오 브리핑용 사건 (사용자 입력 그대로 — LLM 구조화 없이 결정적으로 만든다)."""
    from app.agents.matcher import RULE_CHANNELS
    from app.schemas import Channel, Duration, EventType

    etype = EventType(event_type)
    on = on or date.today()
    desc = description.strip()
    return Event(id=f"scenario_{datetime.now():%Y%m%d_%H%M%S}_{etype.value}", date=on,
                 title=title.strip() or (desc.splitlines()[0][:80] if desc else etype.value), summary=desc or etype.value,
                 type=etype, channels=[Channel(c) for c in channels] if channels else RULE_CHANNELS[etype],
                 regions=regions or [], entities=entities or [], duration=Duration(duration), severity=severity,
                 sources=["사용자 입력 (가정 시나리오)"])


def run_scenario(event: Event, portfolio=None, holdings: list[dict] | None = None, playbooks: list | None = None) -> Briefing:
    """가정 시나리오 브리핑. 시장·자금 신호는 커밋된 FRED 캐시의 최신값."""
    from app.config import get_settings

    llm = LLMClient(db_mode="sandbox")
    b = orchestrator.run_scenario_briefing(event, load_panel(sentinel.panel_series_ids()), llm, portfolio=portfolio,
                                           holdings=holdings, playbooks=playbooks)
    audit_briefing(b, "scenario", get_settings().llm_provider, portfolio, playbooks)
    return b


def is_scenario(b: Briefing) -> bool:
    return b.event.id.startswith("scenario_")


def briefing_kind(b: Briefing) -> str:
    """auto(자동 감시 사건) / ondemand(직접 실행, 사건 미확인) / scenario(가정 사건)."""
    return "scenario" if b.event.id.startswith("scenario_") else "ondemand" if b.event.id.startswith("ondemand_") else "auto"


def ondemand_topics(signals: dict) -> tuple[list[str], str | None, str]:
    """직접 실행 브리핑의 주제 후보와 기본값·선택 이유. 신호 dict = 글로벌 수집 결과 또는 로컬 kr_latest."""
    news = signals.get("news") or signals.get("kr_news") or {}
    obs = news.get("observations") or {}
    topics = list(obs)
    if news.get("clusters"):
        top = news["clusters"][0]["event_type"]
        return topics, top, "기사량 급증으로 탐지된 사건"
    scored = [(t, o["z"]) for t, o in obs.items() if o.get("z") is not None]
    if scored:
        t, z = max(scored, key=lambda x: x[1])
        return topics, t, f"급증 기준 미만이지만 평소 대비 가장 높은 주제 (z {z:+.2f})"
    if obs:
        t = max(obs, key=lambda k: obs[k].get("n_articles", 0))
        return topics, t, f"기준선이 쌓이는 중이라 기사 수가 가장 많은 주제 ({obs[t].get('n_articles', 0)}건)"
    return topics, None, "뉴스 관측 없음"


def ondemand_event(signals: dict, topic: str, local: bool, on: date | None = None) -> Event:
    """현재 감시 신호(뉴스 관측·시장 z)를 근거로 직접 실행 브리핑용 사건을 만든다 (LLM 구조화 없이 결정적)."""
    from app.agents.matcher import RULE_CHANNELS
    from app.schemas import Duration, EventType

    news = signals.get("news") or signals.get("kr_news") or {}
    o = (news.get("observations") or {}).get(topic, {})
    market = signals.get("market") or signals.get("kr_market") or {}
    z = market.get("zscores") or {}
    level = signals.get("level", "NONE")
    lines = [f"현재 감시 등급 {level}. 자동 감시가 사건을 확인하지 않은 상태에서 사용자가 직접 실행했다." if not news.get("clusters")
             else f"현재 감시 등급 {level}. 기사량 급증으로 탐지된 사건."]
    if o:
        lines.append(f"{topic} 관련 최근 24시간 기사 {o.get('n_articles', 0)}건·언론사 {o.get('n_sources', 0)}곳"
                     + (f", 평소 대비 z {o['z']:+.2f}" if o.get("z") is not None else ", 기준선 축적 중"))
    lines += [f"- {t}" for t in (o.get("top_titles") or [])[:3]]
    if z:
        top = sorted(((k, v) for k, v in z.items() if v is not None), key=lambda kv: -abs(kv[1]))[:3]
        lines.append("시장 z: " + ", ".join(f"{k} {v:+.2f}" for k, v in top))
    etype = EventType(topic) if topic in EventType._value2member_map_ else EventType.other
    on = on or date.today()
    return Event(id=f"ondemand_{datetime.now():%Y%m%d_%H%M%S}_{etype.value}", date=on,
                 title=f"현재 신호 점검 — {etype.value} ({'대한민국' if local else '글로벌'}, {on})", summary="\n".join(lines),
                 type=etype, channels=RULE_CHANNELS[etype], regions=["KR"] if local else ["GLOBAL"],
                 duration=Duration.weeks, severity={"ALERT": 4, "WATCH": 3}.get(level, 2),
                 sources=["감시 신호 (Google 뉴스 RSS·FRED·ECOS)"])


def run_ondemand(event: Event, portfolio=None, holdings: list[dict] | None = None, playbooks: list | None = None) -> Briefing:
    """직접 실행 브리핑 (사건 미확인 상태 포함). sandbox 기록, 감사 로그 mode=ondemand."""
    llm = LLMClient(db_mode="sandbox")
    b = orchestrator.run_scenario_briefing(event, load_panel(sentinel.panel_series_ids()), llm, portfolio=portfolio,
                                           holdings=holdings, playbooks=playbooks, note_head=orchestrator.ONDEMAND_NOTE)
    audit_briefing(b, "ondemand", get_settings().llm_provider, portfolio, playbooks)
    return b


def audit_briefing(b: Briefing, mode: str, provider: str, portfolio=None, playbooks: list | None = None,
                   source: str = "app") -> None:
    """브리핑 생성 감사 기록: 무엇을 근거로 어떤 문서를 올렸는지 (보유 종목명은 남기지 않는다)."""
    payload = b.model_dump_json().encode("utf-8")
    audit.log("briefing", {"run_id": b.run_id, "trace_id": b.trace_id, "mode": mode, "event_id": b.event.id,
                           "event_type": b.event.type.value, "provider": provider,
                           "top_docs": [[f.doc_id, f.fit_score] for f in b.match.doc_fits[:3]],
                           "uploaded_portfolio": portfolio is not None, "uploaded_docs": len(playbooks or []),
                           "briefing_sha256": audit.sha256_bytes(payload)}, source=source)


def run_replay(event_id: str, portfolio=None, holdings: list[dict] | None = None, playbooks: list | None = None) -> Briefing:
    """백테스트 사건 재생 → Briefing (sandbox). portfolio·playbooks를 주면 업로드 데이터로 가정 분석."""
    from app.config import get_settings

    b = orchestrator.run_replay(event_id, portfolio=portfolio, holdings=holdings, playbooks=playbooks)
    audit_briefing(b, "replay", get_settings().llm_provider, portfolio, playbooks)
    return b


def load_saved_briefing(event_id: str) -> Briefing | None:
    """커밋된 재생 결과 (앱 시작 직후에도 바로 표시용)."""
    path = BACKTEST_DIR / "briefings" / f"{event_id}.json"
    if not path.exists():
        return None
    return Briefing.model_validate(json.loads(path.read_text(encoding="utf-8"))["briefing"])


def _find_mode(run_id: str) -> DbMode | None:
    for mode in ("live", "sandbox"):
        conn = connect(mode)
        hit = conn.execute("SELECT 1 FROM briefings WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        if hit:
            return mode
    return None


def get_briefing(run_id: str) -> Briefing | None:
    mode = _find_mode(run_id)
    return orchestrator.get_briefing(run_id, mode) if mode else None


def get_trace(trace_id: str) -> list[dict]:
    for mode in ("live", "sandbox"):
        rows = orchestrator.get_trace(trace_id, mode)
        if rows:
            return rows
    return []


def submit_feedback(fb: Feedback, briefing: Briefing | None = None) -> None:
    """피드백 저장 + shadow_log 갱신. 브리핑이 DB에 없으면(커밋된 결과) sandbox에 기록한다."""
    mode: DbMode = _find_mode(fb.run_id) or "sandbox"
    briefing = briefing or orchestrator.get_briefing(fb.run_id, mode)
    rank = next((i for i, f in enumerate(briefing.match.doc_fits, start=1) if f.doc_id == fb.doc_id), None) if briefing else None
    conn = connect(mode)
    with conn:
        conn.execute("INSERT INTO feedback (run_id, doc_id, label, user_id, ts) VALUES (?, ?, ?, ?, ?)",
                     (fb.run_id, fb.doc_id, fb.label, fb.user_id, fb.ts.isoformat()))
        if briefing:
            conn.execute(
                "INSERT INTO shadow_log (event_id, doc_id, event_type, cited, rank, feedback, mode, ts) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                (briefing.event.id, fb.doc_id, briefing.event.type.value, rank, fb.label,
                 "live" if mode == "live" else "backtest", fb.ts.isoformat()),
            )
    conn.close()
    audit.log("feedback", {"run_id": fb.run_id, "doc_id": fb.doc_id, "label": fb.label, "rank": rank}, actor=fb.user_id)


def learner_enabled() -> bool:
    from app.agents import learner

    return learner.is_enabled()


def get_priority(mode: DbMode = "sandbox") -> dict:
    """문서별 인용·피드백 집계 (shadow_log)와 학습 층 상태."""
    conn = connect(mode)
    rows = [dict(r) for r in conn.execute(
        "SELECT doc_id, SUM(cited) AS cited, SUM(feedback = 'useful') AS useful, SUM(feedback = 'not_fit') AS not_fit, "
        "COUNT(DISTINCT event_id) AS events FROM shadow_log GROUP BY doc_id ORDER BY cited DESC, doc_id")]
    conn.close()
    return {"learner_enabled": learner_enabled(), "engine": "plans.md 5.4 (app/agents/learner.py)", "docs": rows}


def set_learner_enabled(enabled: bool, mode: DbMode = "sandbox") -> dict:
    """학습 층 토글. 변경은 learner_toggle_log에 기록한다."""
    from app.agents import learner

    learner.set_enabled(enabled, mode)
    return {"ok": True, "enabled": enabled}


def get_backtest_results() -> dict:
    """커밋된 백테스트 결과 (P8의 backtest_results.json이 생기면 함께 반환)."""
    def read(name: str):
        path = BACKTEST_DIR / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    exposure = {}
    for path in sorted((BACKTEST_DIR / "exposure").glob("*.json")):
        exposure[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return {
        "sentinel": read("sentinel_results.json"),
        "match": read("match_summary.json"),
        "exposure": exposure,
        "backtest": read("../backtest_results.json"),
        "learner": read("learner_results.json"),
        "kr": read("kr_results.json"),
        "v6": read("v6_results.json"),
        "clause_eval": read("clause_eval.json"),
    }


def record_approval(briefing: Briefing, decision: str, user_id: str, note: str = "") -> None:
    """브리핑 승인·반려 (사람의 최종 결정)를 trace에 남긴다."""
    mode: DbMode = _find_mode(briefing.run_id) or "sandbox"
    conn = connect(mode)
    with conn:
        step = conn.execute("SELECT COALESCE(MAX(step), 0) + 1 FROM traces WHERE trace_id = ?", (briefing.trace_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO traces (trace_id, step, tool, input_summary, output_summary, ts) VALUES (?, ?, 'human_approval', ?, ?, ?)",
            (briefing.trace_id, step, json.dumps({"user_id": user_id, "note": note}, ensure_ascii=False), decision,
             datetime.now(timezone.utc).isoformat()),
        )
    conn.close()
    audit.log("approval", {"run_id": briefing.run_id, "trace_id": briefing.trace_id, "event_id": briefing.event.id,
                           "decision": decision, "note": note}, actor=user_id)
