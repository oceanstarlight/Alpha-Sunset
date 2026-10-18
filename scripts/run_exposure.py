"""P5 Exposure 재생: 사건별 상위 노출 경로 + why.

gfc_2008은 N-PORT 스냅샷이 없어 제외한다 (plans.md 11장).
결과: data/backtest/exposure/{event_id}.json
사용: python -m scripts.run_exposure [--event svb_2023]
"""

from __future__ import annotations

import argparse
import json

from app.agents.exposure import ExposureUnavailable, compute_exposure
from app.config import ROOT_DIR
from app.corpus import load_events, load_portfolio
from app.llm.client import LLMClient

OUT_DIR = ROOT_DIR / "data" / "backtest" / "exposure"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event")
    args = parser.parse_args()

    llm = LLMClient(db_mode="sandbox")
    portfolio = load_portfolio()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for e in sorted(load_events(), key=lambda e: e.date):
        if args.event and e.id != args.event:
            continue
        try:
            rep = compute_exposure(e, portfolio, llm)
        except ExposureUnavailable as err:
            print(f"{e.id:14s} 제외: {err}")
            continue
        out = {
            "event_id": rep.event_id, "snapshot": rep.snapshot, "uncertain_ratio": rep.uncertain_ratio,
            "needs_requery": rep.needs_requery, "entity_matches": rep.entity_matches,
            "portfolio_nodes": rep.portfolio_nodes, "paths": [p.model_dump() for p in rep.paths],
            "entity_paths": [p.model_dump() for p in rep.entity_paths],
        }
        (OUT_DIR / f"{e.id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n{e.id}  불확실 비율 {rep.uncertain_ratio}  이름매칭 {rep.entity_matches}")
        for p in rep.entity_paths:
            print(f"  [동일 발행자] {p.risk_score:.5f}  {' → '.join(p.nodes[1:])}")
        for p in rep.paths[:5]:
            print(f"  {p.risk_score:.5f}  {' → '.join(p.nodes[1:])}")
            print(f"           {p.why}")


if __name__ == "__main__":
    main()
