"""글로벌 시그널 수집기 (GitHub Actions에서 3시간마다 → data/live/ 커밋).

- A·C: FRED (임시 폴더에 내려받아 커밋된 data/fred 캐시를 바꾸지 않는다 — 백테스트 재현성)
- B: Google 뉴스 RSS(영문) 주제별 최근 24시간 기사 수·언론사 수. 이번 관측을 global_news_history.jsonl에 쌓아
  같은 시간대 기준선(직전 30일)을 만든다. GDELT는 공유 IP 요청 제한(429)이 잦아 쓰지 않는다 (사용자 결정).

    .venv/bin/python scripts/collect_signals.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import services  # noqa: E402

LIVE_DIR = services.LIVE_SIGNALS_PATH.parent
HISTORY_PATH = LIVE_DIR / "signals_history.jsonl"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        result = services.compute_signals(fred_cache_dir=Path(tmp))
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
                "clusters": [c["event_type"] for c in result["news"]["clusters"]]}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
