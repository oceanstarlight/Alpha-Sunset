"""ECOS 일별 이력 수집 → data/ecos/{series}.csv (한국 신호 백테스트용, 사전 등록 v5).

    python scripts/fetch_ecos.py   # ECOS_API_KEY 필요
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT_DIR, load_config  # noqa: E402
from app.data.korea import EcosClient  # noqa: E402

OUT = ROOT_DIR / "data" / "ecos"


def main() -> int:
    cfg = load_config()["korea"]
    specs = {**cfg["market"]["series"], **cfg["flow"]["series"]}
    OUT.mkdir(parents=True, exist_ok=True)
    client = EcosClient()
    for sid, spec in specs.items():
        s = client.series(spec["stat"], spec["item"], date(1995, 1, 1), date.today())
        s.name = sid
        s.to_csv(OUT / f"{sid}.csv")
        print(f"{sid}: {len(s)}행 {s.index[0].date()}~{s.index[-1].date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
