"""UI(Streamlit)가 직접 호출하는 서비스 함수 모음 (plans.md 6장)."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

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


def compute_signals(gdelt_client: Any = None, fred_cache_dir: Path | None = None, coverage: bool = False) -> dict:
    """최신 시그널 A/B/C와 등급을 계산한다. coverage=True면 GDELT 보도 국가 분포도 모은다 (요청 수 2배)."""
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
    if gdelt_client is None:
        from app.data.gdelt import GdeltClient

        gdelt_client = GdeltClient()
    news = sentinel.live_news_signal(gdelt_client, today)
    news_out = {"active": news.active, "status": news.status, "n_queries": news.n_queries, "errors": news.errors,
                "clusters": [c.__dict__ for c in news.clusters]}
    if coverage:
        from app import geo

        news_out["coverage"] = geo.gdelt_coverage(gdelt_client)
    level = sentinel.grade(market, news, flow)
    chain = sentinel.explain(sentinel.SentinelResult(as_of=last_obs, level=level, market=market, news=news, flow=flow))
    return {
        "fetched_at": time.time(),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": last_obs.isoformat(),
        "level": level.value,
        "chain": chain,  # 원인-근거-결과
        # 1단계: 자금·시장 이상 알림 (사건 확정 전), 2단계: 사건 확정 시 대응안(ALERT)
        "money_alert": market.active or bool(flow and flow.active),
        "market": {"active": market.active, "triggered": market.triggered,
                   "zscores": {k: round(v, 2) for k, v in market.zscores.items()}},
        "flow": {"active": flow.active, "triggered": flow.triggered,
                 "zscores": {k: round(v, 2) for k, v in flow.zscores.items()}} if flow else None,
        "news": news_out,
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


def get_signals(refresh: bool = False, gdelt_client: Any = None) -> dict:
    """refresh=False면 일일 수집 결과를 쓰고, 없거나 refresh=True면 직접 조회한다 (1시간 캐시)."""
    if not refresh:
        collected = load_collected_signals()
        if collected:
            return collected
    cached = _signal_cache.get("signals")
    if cached and not refresh and time.time() - cached["fetched_at"] < SIGNAL_TTL_SEC:
        return cached
    result = compute_signals(gdelt_client)
    result["source"] = "live"
    _signal_cache["signals"] = result
    return result


def run_live(signals: dict | None = None) -> Briefing | None:
    """현재 사건 탐지 → Briefing. 사건 신호(B)가 없으면 None."""
    signals = signals or get_signals()
    clusters = signals["news"]["clusters"]
    if not clusters:
        return None
    top = clusters[0]
    llm = LLMClient(db_mode="live")
    text = f"{top['label']}\n(뉴스 군집: {top['event_type']}, 기사 {top['n_articles']}건, 출처 {top['n_sources']}곳)"
    event = structure_event(llm, text, f"live_{date.today():%Y%m%d}_{top['event_type']}", date.today())
    return orchestrator.run_live_briefing(event, signals["panel"], llm)


def run_replay(event_id: str) -> Briefing:
    """백테스트 사건 재생 → Briefing (sandbox)."""
    return orchestrator.run_replay(event_id)


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
