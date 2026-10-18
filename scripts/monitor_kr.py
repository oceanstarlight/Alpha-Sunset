"""로컬(대한민국) 상시 감시 — GitHub Actions에서 30분마다(뉴스·DART), 하루 2회 --daily(ECOS 시장·자금).

    .venv/bin/python scripts/monitor_kr.py            # 뉴스·DART
    .venv/bin/python scripts/monitor_kr.py --daily    # + ECOS 시장·외국인 순매수 갱신

키가 없는 소스는 '미설정'으로 기록하고 건너뛴다. 결과:
- data/live/kr_latest.json (커밋 대상: --daily이거나 등급·경고가 있을 때만 갱신)
- data/live/reports/*.md (대응안 리포트)
- .kr_state/ (Actions 캐시: 뉴스 기준선·마지막 시장 신호·알림 중복 방지 상태, 커밋 안 함)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app.agents import local  # noqa: E402
from app.agents.sentinel import AlertLevel, MarketSignal  # noqa: E402
from app.config import ROOT_DIR, load_config  # noqa: E402
from app.data import korea  # noqa: E402
from app.notify import Notifier, format_message  # noqa: E402
from app.report import build_report, save_report  # noqa: E402

LIVE_DIR = ROOT_DIR / "data" / "live"
STATE_DIR = ROOT_DIR / ".kr_state"
NEWS_HISTORY = STATE_DIR / "kr_news_history.jsonl"
KR_PANEL_DIR = STATE_DIR / "ecos"
KR_SIGNALS = STATE_DIR / "kr_signals.json"
RUN_STATE = STATE_DIR / "run_state.json"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def refresh_ecos(today: date) -> tuple[dict[str, pd.Series], list[str]]:
    """ECOS 일별 시리즈를 받아 상태 폴더에 저장. 실패하면 이전 저장본."""
    cfg = load_config()["korea"]
    client, notes = korea.EcosClient(), []
    raw: dict[str, pd.Series] = {}
    specs = {**cfg["market"]["series"], **cfg["flow"]["series"]}
    KR_PANEL_DIR.mkdir(parents=True, exist_ok=True)
    for sid, spec in specs.items():
        path = KR_PANEL_DIR / f"{sid}.csv"
        try:
            s = client.series(spec["stat"], spec["item"], today - timedelta(days=365 * 7), today)
            s.to_csv(path)
        except korea.KeyMissing as e:
            notes.append(str(e))
        except Exception as e:
            notes.append(f"ECOS {sid}: {e}")
        if path.exists():
            raw[sid] = pd.read_csv(path, index_col=0, parse_dates=True).iloc[:, 0]
    return raw, sorted(set(notes))


def load_kr_panel() -> dict[str, pd.Series]:
    return {p.stem: pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0] for p in KR_PANEL_DIR.glob("*.csv")}


def global_state() -> tuple[bool, MarketSignal | None, list[str]]:
    """글로벌 수집기(collect_signals.py) 결과에서 해외 사건·시장 신호."""
    path = LIVE_DIR / "signals_latest.json"
    if not path.exists():
        return False, None, []
    g = json.loads(path.read_text(encoding="utf-8"))
    m = g["market"]
    market = MarketSignal(as_of=date.fromisoformat(g["as_of"]), zscores=m["zscores"], triggered=m["triggered"], active=m["active"])
    return bool(g["news"]["active"]), market, [c["event_type"] for c in g["news"]["clusters"]]


def try_briefing(result: local.LocalResult, global_types: list[str]):
    """로컬 ALERT → 대응안 브리핑 (Gemini 필요). 실패하면 None (리포트는 판단 근거만으로 생성)."""
    try:
        from app.agents import orchestrator
        from app.agents.matcher import structure_event
        from app.data.fred import load_panel
        from app.agents import sentinel
        from app.llm.client import LLMClient

        parts = [f"{c.event_type}: " + " / ".join(c.top_titles) for c in (result.kr_news.clusters if result.kr_news else [])]
        parts += [f"{w.disclosure.corp_name} {w.disclosure.report_nm}" for w in result.warnings if w.confirmed]
        parts += [f"해외 사건 신호: {t}" for t in global_types]
        llm = LLMClient(db_mode="live")
        event = structure_event(llm, "\n".join(parts), f"live_kr_{date.today():%Y%m%d}", date.today())
        return orchestrator.run_live_briefing(event, load_panel(sentinel.panel_series_ids()), llm)
    except Exception as e:
        print(f"브리핑 생성 실패: {type(e).__name__}: {e}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily", action="store_true", help="ECOS 시장·외국인 순매수 갱신")
    args = ap.parse_args()
    cfg = load_config()["korea"]
    now = datetime.now(korea.KST)
    STATE_DIR.mkdir(exist_ok=True)
    run_state = json.loads(RUN_STATE.read_text()) if RUN_STATE.exists() else {"failure_streak": 0, "last_level": "NONE"}
    notes: list[str] = []

    # A_kr · C_kr (하루 2회 갱신, 그 사이에는 마지막 값)
    if args.daily:
        raw, ecos_notes = refresh_ecos(now.date())
        notes += ecos_notes
    else:
        raw = load_kr_panel()
    panel = local.kr_panel(raw)
    kr_market = local.kr_market_signal(panel, now.date()) if panel else None
    kr_market = kr_market if kr_market and kr_market.zscores else None
    kr_flow = local.kr_flow_signal(panel, now.date()) if panel else None

    # B_kr 뉴스
    google = korea.GoogleNewsRss()
    since = now - timedelta(hours=cfg["news"]["window_hours"])
    articles, news_notes = {}, []
    for event_type, query in cfg["news"]["queries"].items():
        items, n = korea.search_news(query, since, google)
        articles[event_type], news_notes = items, news_notes + n
    history = _read_jsonl(NEWS_HISTORY)
    kr_news, rows = local.kr_news_signal(articles, history, now, sorted(set(news_notes)))
    with NEWS_HISTORY.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)

    # DART 신용 공시 → 경고, 기업명 기사로 확정 판정
    warnings = []
    try:
        disclosures = korea.DartClient().disclosures(now.date() - timedelta(days=2), now.date())
        for w in local.dart_warnings(disclosures):
            corp_items, n = korea.search_news(w.disclosure.corp_name, now - timedelta(hours=cfg["dart"]["confirm_hours"] + 24), google)
            notes += n
            warnings.append(local.confirm_warning(w, corp_items, now))
    except korea.KeyMissing as e:
        notes.append(str(e))
    except Exception as e:
        notes.append(f"DART: {e}")

    # 해외 사건 + 연관성 근거
    global_active, global_market, global_types = global_state()
    linkage = None
    if global_active and kr_market and global_market:
        from app.data.fred import load_panel
        from app.agents import sentinel

        links = local.historical_link(load_panel(sentinel.panel_series_ids()), panel, now.date())
        linkage = local.linkage_evidence(global_market, kr_market, links)  # 글로벌 수집은 하루 1회라 t−1 신호는 global_market 자체

    level = local.local_grade(kr_market, kr_flow, kr_news, global_active, warnings)
    result = local.LocalResult(now, level, kr_market, kr_flow, kr_news, global_active, warnings, linkage)
    chain = local.explain_local(result)

    # 수집 실패 연속 (키 미설정·기준선 축적은 실패가 아님)
    real_failures = [x for x in notes + news_notes if "미설정" not in x]
    run_state["failure_streak"] = run_state["failure_streak"] + 1 if real_failures else 0

    # 알림
    notifier = Notifier(STATE_DIR / "notify_state.json")
    sent = {}
    repo = os.environ.get("GITHUB_REPOSITORY")
    report_link = None
    if level == AlertLevel.ALERT:
        briefing = try_briefing(result, global_types)
        name = f"{now:%Y%m%d_%H%M}_kr_alert"
        save_report(build_report(f"로컬 대응안 리포트 {now:%Y-%m-%d %H:%M}", now, chain, linkage, briefing), LIVE_DIR / "reports", name)
        report_link = f"https://github.com/{repo}/blob/main/data/live/reports/{name}.md" if repo else f"data/live/reports/{name}.md"
        key = "alert:" + ",".join(sorted({c.event_type for c in kr_news.clusters} | set(global_types)))
        sent[key] = notifier.send(key, format_message("🔴 2단계: 대응안", chain, report_link))
    elif result.money_alert:
        sent[f"money:{now.date()}"] = notifier.send(f"money:{now.date()}", format_message("🟠 1단계: 자금 이상 알림", chain))
    for w in warnings:
        key = f"dart:{w.disclosure.rcept_no}:{w.confirmed}"
        sent[key] = notifier.send(key, format_message(f"🟡 사건 경고: {w.disclosure.corp_name} {w.keyword}", chain))
    if run_state["failure_streak"] >= cfg["alerts"]["failure_streak_warn"]:
        sent["failure"] = notifier.send(f"failure:{now.date()}", format_message(
            "⚠️ 감시 공백: 수집 실패 연속 " + str(run_state["failure_streak"]) + "회",
            [{"단계": "수집", "원인": "; ".join(real_failures[:5]), "근거": "연속 실패 횟수 기준 (사전 등록 v5)", "결과": "감시 공백 경고"}]))

    # 저장 (커밋 대상은 의미 있는 변화가 있을 때만)
    out = local.to_json(result) | {"notes": sorted(set(notes)), "alerts_sent": sent, "report": report_link}
    changed = args.daily or level.value != run_state["last_level"] or bool(warnings) or report_link is not None
    if changed:
        local.write_json(LIVE_DIR / "kr_latest.json", out)
    run_state["last_level"] = level.value
    RUN_STATE.write_text(json.dumps(run_state))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"commit={'true' if changed else 'false'}\n")
    print(json.dumps({"level": level.value, "money_alert": result.money_alert, "news_status": kr_news.status,
                      "warnings": len(warnings), "alerts_sent": sent, "notes": sorted(set(notes))[:10],
                      "news_notes": sorted(set(news_notes))[:5]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
