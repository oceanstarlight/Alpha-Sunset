"""ECOS 항목 코드 확인 (config.yaml korea.market/flow의 stat·item이 실제 일별 항목인지).

    python scripts/check_ecos.py   # ECOS_API_KEY 필요. 키는 출력하지 않는다
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import get_secret, load_config  # noqa: E402

URL = "https://ecos.bok.or.kr/api/StatisticItemList/{key}/json/kr/1/500/{stat}"


def main() -> int:
    key = get_secret("ECOS_API_KEY")
    if not key:
        print("ECOS_API_KEY 미설정")
        return 1
    cfg = load_config()["korea"]
    wanted = {**cfg["market"]["series"], **cfg["flow"]["series"]}
    ok = True
    for stat in sorted({s["stat"] for s in wanted.values()}):
        rows = httpx.get(URL.format(key=key, stat=stat), timeout=60).json().get("StatisticItemList", {}).get("row", [])
        print(f"\n## {stat} ({rows[0]['STAT_NAME'] if rows else '항목 없음'})")
        for r in rows:
            if r["CYCLE"] == "D":
                print(f"  {r['ITEM_CODE']:<12} {r['ITEM_NAME']}  ({r.get('START_TIME')}~{r.get('END_TIME')})")
        codes = {r["ITEM_CODE"]: r["ITEM_NAME"] for r in rows if r["CYCLE"] == "D"}
        for sid, spec in wanted.items():
            if spec["stat"] == stat:
                hit = codes.get(spec["item"])
                ok &= hit is not None
                print(f"  -> {sid}: {spec['item']} = {hit or '없음 (코드 수정 필요)'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
