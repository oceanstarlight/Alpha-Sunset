"""글로벌 시그널 수집기 (GitHub Actions에서 3시간마다 → data/live/ 커밋).

GitHub Actions도 공유 IP라 GDELT 요청 제한(429)에 자주 걸린다. 그래서 한 번에 다 받지 않고
- 주제별로 따로 받아 결과를 data/live/gdelt_topics.json에 쌓고 (실패한 주제는 이전 성공값 유지)
- 요청 사이를 60초 이상 띄우고, 429면 2·3·4분 더 기다린다
- 실행당 시간 예산(기본 35분)을 넘기면 남은 주제는 다음 실행으로 미룬다
- 최근 5시간 안에 성공한 주제는 다시 받지 않는다
보도 국가 분포는 위기 키워드를 하나의 OR 쿼리로 묶어 요청 1회로 받는다.
FRED는 임시 폴더에 내려받는다 (커밋된 data/fred 캐시를 바꾸면 백테스트 재현성이 깨질 수 있음).

    .venv/bin/python scripts/collect_signals.py [--interval 60] [--budget-min 35]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import geo, services  # noqa: E402
from app.agents import sentinel  # noqa: E402
from app.config import load_config  # noqa: E402

LIVE_DIR = services.LIVE_SIGNALS_PATH.parent
HISTORY_PATH = LIVE_DIR / "signals_history.jsonl"
TOPICS_PATH = LIVE_DIR / "gdelt_topics.json"
REFRESH_HOURS = 5


def collect_topics(client, state: dict, today: date, now: datetime, budget_sec: float) -> dict:
    """오래된 주제부터 하나씩 받는다. 예산을 넘기면 멈춘다."""
    queries = load_config()["sentinel"]["news"]["queries"]

    def age(t):  # 오래된(또는 실패한) 주제 먼저
        ok = state.get(t, {}).get("ok_at")
        return (now - datetime.fromisoformat(ok)).total_seconds() if ok else float("inf")

    start = time.monotonic()
    for event_type in sorted(queries, key=age, reverse=True):
        if age(event_type) < REFRESH_HOURS * 3600:
            continue
        if time.monotonic() - start > budget_sec:
            print(f"시간 예산 초과 → {event_type} 이후는 다음 실행으로")
            break
        entry = state.setdefault(event_type, {})
        entry["tried_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            entry["result"] = sentinel.news_topic(client, event_type, queries[event_type], today)
            entry["ok_at"], entry["error"] = entry["tried_at"], None
            print(f"{event_type}: 성공 z={entry['result']['z']}")
        except Exception as e:
            entry["error"] = str(e)[:200]
            print(f"{event_type}: 실패 {entry['error']}")
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=60, help="GDELT 요청 간격(초)")
    ap.add_argument("--budget-min", type=float, default=35, help="GDELT 수집 시간 예산(분)")
    args = ap.parse_args()
    from app.data.gdelt import GdeltClient

    client = GdeltClient(interval_sec=args.interval)
    now = datetime.now(timezone.utc)
    today = date.today()
    state = json.loads(TOPICS_PATH.read_text(encoding="utf-8")) if TOPICS_PATH.exists() else {}
    state = collect_topics(client, state, today, now, args.budget_min * 60)
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    TOPICS_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    news = sentinel.news_signal_from_topics(state, today, datetime.now(timezone.utc))
    coverage = geo.gdelt_coverage_combined(client)
    prev = json.loads(services.LIVE_SIGNALS_PATH.read_text(encoding="utf-8")) if services.LIVE_SIGNALS_PATH.exists() else {}
    if coverage["status"] == "unavailable" and prev.get("news", {}).get("coverage", {}).get("status") == "ok":
        coverage = prev["news"]["coverage"] | {"stale_since": prev.get("collected_at")}  # 이전 성공값 유지
    with tempfile.TemporaryDirectory() as tmp:
        result = services.compute_signals(fred_cache_dir=Path(tmp), news=news, coverage_data=coverage)
    result.pop("panel")
    result.pop("fetched_at")
    result["news"]["topics"] = {k: {"ok_at": v.get("ok_at"), "z": (v.get("result") or {}).get("z"), "error": v.get("error")}
                                for k, v in state.items()}
    services.LIVE_SIGNALS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("collected_at", "as_of", "level", "money_alert")}
    summary |= {"market": result["market"]["triggered"], "flow": (result["flow"] or {}).get("triggered", []),
                "news_status": result["news"]["status"], "news_errors": len(result["news"]["errors"]),
                "clusters": [c["event_type"] for c in result["news"]["clusters"]],
                "coverage_status": coverage["status"]}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
