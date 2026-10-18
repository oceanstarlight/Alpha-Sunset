"""P6 재생: 사건별 run_replay → Briefing + trace.

결과: data/backtest/briefings/{event_id}.json (브리핑 + 도구 호출 trace)
사용: python -m scripts.run_replay [--event svb_2023]
"""

from __future__ import annotations

import argparse
import json

from app.agents.orchestrator import get_trace, run_replay
from app.config import ROOT_DIR
from app.corpus import load_events

OUT_DIR = ROOT_DIR / "data" / "backtest" / "briefings"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for e in sorted(load_events(), key=lambda e: e.date):
        if args.event and e.id != args.event:
            continue
        b = run_replay(e.id)
        trace = get_trace(b.trace_id)
        out = {"briefing": json.loads(b.model_dump_json()), "trace": [{k: r[k] for k in ("step", "tool")} for r in trace]}
        (OUT_DIR / f"{e.id}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        steps = " → ".join(r["tool"] for r in trace)
        top = ", ".join(f"{f.doc_id}({f.fit_score:.2f})" for f in b.match.doc_fits[:3])
        print(f"{e.id:14s} {b.alert_level.value:5s} top3 {top}  노출 {len(b.exposure_top)}  확인항목 {len(b.actions_to_check)}")
        print(f"               trace: {steps}")


if __name__ == "__main__":
    main()
