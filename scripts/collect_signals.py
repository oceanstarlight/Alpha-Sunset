"""글로벌 시그널 수집기 (GitHub Actions에서 3시간마다 → data/live/ 커밋).

- A·C: FRED (임시 폴더에 내려받아 커밋된 data/fred 캐시를 바꾸지 않는다 — 백테스트 재현성)
- B: Google 뉴스 RSS(영문) 주제별 최근 24시간 기사 수·언론사 수. 이번 관측을 global_news_history.jsonl에 쌓아
  기준선(직전 30일)을 만든다. GDELT는 공유 IP 요청 제한(429)이 잦아 쓰지 않는다 (사용자 결정).
- 알림(텔레그램, 원인-근거-결과): 1단계 자금 이상(하루 1번), 2단계 ALERT(대응안 리포트 생성·링크), 뉴스 조회 전부 실패
  (하루 1번). 중복 방지 기록은 data/live/global_notify_state.json.

    .venv/bin/python scripts/collect_signals.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import audit, services  # noqa: E402
from app.notify import Notifier, format_message  # noqa: E402
from app.report import build_report, save_report  # noqa: E402

LIVE_DIR = services.LIVE_SIGNALS_PATH.parent
HISTORY_PATH = LIVE_DIR / "signals_history.jsonl"


def notify(result: dict) -> dict:
    """글로벌 알림. 반환: 키 → 발송 결과."""
    now = datetime.now(timezone.utc)
    notifier = Notifier(LIVE_DIR / "global_notify_state.json")
    chain, news, sent = result["chain"], result["news"], {}
    if result["level"] == "ALERT":
        briefing = None
        try:
            briefing = services.run_live(result, audit_source="collect_signals")  # Gemini 필요. 실패하면 판단 근거만으로 리포트
        except Exception as e:
            print(f"브리핑 생성 실패: {type(e).__name__}: {e}")
        name = f"{now:%Y%m%d_%H%M}_global_alert"
        save_report(build_report(f"글로벌 대응안 리포트 {now:%Y-%m-%d %H:%M} UTC", now, chain, None, briefing),
                    LIVE_DIR / "reports", name)
        repo = os.environ.get("GITHUB_REPOSITORY")
        link = f"https://github.com/{repo}/blob/main/data/live/reports/{name}.md" if repo else f"data/live/reports/{name}.md"
        key = "global_alert:" + ",".join(sorted(c["event_type"] for c in news["clusters"]))
        sent[key] = notifier.send(key, format_message("🔴 글로벌 2단계: 대응안", chain, link))
    elif result["money_alert"]:
        key = f"global_money:{now.date()}"
        sent[key] = notifier.send(key, format_message("🟠 글로벌 1단계: 자금 이상 알림", chain))
    fetch_fail = [e for e in news["errors"] if "RSS 실패" in e]
    if len(fetch_fail) >= news["n_queries"]:
        key = f"global_news_fail:{now.date()}"
        sent[key] = notifier.send(key, format_message("⚠️ 글로벌 뉴스 조회 전부 실패 (감시 공백)", [
            {"단계": "사건 신호(B)", "원인": "; ".join(fetch_fail[:3]), "근거": "Google 뉴스 RSS 8주제 모두 실패", "결과": "판단 불가"}]))
    return sent


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        result = services.compute_signals(fred_cache_dir=Path(tmp))
    result["alerts_sent"] = notify(result)
    audit.log("signal_run", {"as_of": result["as_of"], "level": result["level"], "money_alert": result["money_alert"],
                             "market": result["market"]["triggered"], "news_status": result["news"]["status"],
                             "clusters": [c["event_type"] for c in result["news"]["clusters"]],
                             "alerts_sent": result["alerts_sent"]}, source="collect_signals")
    result.pop("panel")
    result.pop("fetched_at")
    rows = result.pop("news_rows")
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    with services.GLOBAL_NEWS_HISTORY.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    services.LIVE_SIGNALS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("collected_at", "as_of", "level", "money_alert")}
    summary |= {"market": result["market"]["triggered"], "flow": (result["flow"] or {}).get("triggered", []),
                "news_status": result["news"]["status"], "news_errors": len(result["news"]["errors"]),
                "clusters": [c["event_type"] for c in result["news"]["clusters"]], "alerts_sent": result["alerts_sent"]}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
