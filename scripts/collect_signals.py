"""일일 시그널 수집기 (GitHub Actions에서 매일 실행 → data/live/ 커밋).

Streamlit Cloud의 공유 IP에서는 GDELT 요청 제한에 자주 걸려서, 하루 1번 느린 간격으로 모아 둔다.
FRED는 임시 폴더에 내려받는다 (커밋된 data/fred 캐시를 바꾸면 백테스트 재현성이 깨질 수 있음).

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
        result = services.compute_signals(fred_cache_dir=Path(tmp), coverage=True)
    result.pop("panel")
    result.pop("fetched_at")
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    services.LIVE_SIGNALS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("collected_at", "as_of", "level", "money_alert")}
    summary |= {"market": result["market"]["triggered"], "flow": (result["flow"] or {}).get("triggered", []),
                "news_status": result["news"]["status"], "news_errors": len(result["news"]["errors"]),
                "clusters": [c["event_type"] for c in result["news"]["clusters"]],
                "coverage_status": result["news"]["coverage"]["status"]}
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
