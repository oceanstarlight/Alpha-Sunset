"""공백 채널 탐지 검증: 사건별 핵심 문서를 빼고 Matcher를 돌려 사전 등록된 정답과 비교.

설계·정답은 data/backtest/ablation/preregistration.json (실행 전에 커밋됨). 결과로 규칙을 바꾸지 않는다.
결과: data/backtest/ablation/results.json
사용: python -m scripts.run_ablation
"""

from __future__ import annotations

import json

from app.agents.matcher import match
from app.backtest import mean_or_none, precision_recall
from app.config import ROOT_DIR, get_settings
from app.corpus import load_events, load_playbooks
from app.llm.client import LLMClient
from app.retrieval import ClauseIndex

DIR = ROOT_DIR / "data" / "backtest" / "ablation"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="results.json", help="결과 파일 이름 (규칙 버전별로 분리)")
    args = parser.parse_args()
    reg = json.loads((DIR / "preregistration.json").read_text(encoding="utf-8"))
    events = {e.id: e.as_of_view() for e in load_events()}
    llm = LLMClient(db_mode="sandbox")
    rows = []
    for r in reg["events"]:
        playbooks = [p for p in load_playbooks() if p.doc_id != r["removed_doc"]]
        index = ClauseIndex(playbooks, llm, path=get_settings().data_dir / "chroma_ablation" / r["event_id"])
        result = match(events[r["event_id"]], index, llm)
        predicted = sorted(g.value for g in result.gaps)
        p, rc = precision_recall(set(predicted), set(r["oracle_gaps"]))
        rows.append({"event_id": r["event_id"], "removed_doc": r["removed_doc"], "oracle_gaps": r["oracle_gaps"],
                     "predicted_gaps": predicted, "precision": p, "recall": rc,
                     "top3": [f.doc_id for f in result.doc_fits[:3]]})
        print(f"{r['event_id']:14s} -{r['removed_doc']:9s} 정답 {r['oracle_gaps']}  예측 {predicted}  P={p} R={rc}")
    out = {"preregistration_registered_at": reg["registered_at"], "events": rows,
           "summary": {"gap_precision": mean_or_none([x["precision"] for x in rows]),
                       "gap_recall": mean_or_none([x["recall"] for x in rows])}}
    (DIR / args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out["summary"])


if __name__ == "__main__":
    main()
