"""사전 등록 v7: 조항 단위 전수 라벨 대비 에이전트 판정 평가 → data/backtest/clause_eval.json.

입력: data/labels/clauses/{event_id}.json (격리 라벨러), data/backtest/briefings/{event_id}.json (커밋된 재생 결과).
사용: python -m scripts.run_clause_eval
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

from app.config import ROOT_DIR

LABELS = ROOT_DIR / "data" / "labels" / "clauses"
BRIEFS = ROOT_DIR / "data" / "backtest" / "briefings"
OUT = ROOT_DIR / "data" / "backtest" / "clause_eval.json"
CLASSES = ["applicable", "partial", "not_applicable"]
ACTION = {"applicable", "partial"}


def f1(p: float | None, r: float | None) -> float | None:
    return None if not p or not r else 2 * p * r / (p + r)


def scores(pairs: list[tuple[str, str]]) -> dict:
    """pairs: (라벨, 에이전트). 정확도·macro F1·kappa·혼동행렬·이진(실행 대상) P/R."""
    n = len(pairs)
    if not n:
        return {"n": 0}
    acc = sum(a == b for a, b in pairs) / n
    per = {}
    for c in CLASSES:
        tp = sum(a == c and b == c for a, b in pairs)
        pp, ap = sum(b == c for _, b in pairs), sum(a == c for a, _ in pairs)
        p, r = (tp / pp if pp else None), (tp / ap if ap else None)
        per[c] = {"precision": None if p is None else round(p, 4), "recall": None if r is None else round(r, 4),
                  "f1": None if f1(p, r) is None else round(f1(p, r), 4), "support": ap}
    macro = [v["f1"] for v in per.values() if v["f1"] is not None]
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in CLASSES)
    kappa = (acc - pe) / (1 - pe) if pe < 1 else None
    tp = sum(a in ACTION and b in ACTION for a, b in pairs)
    pp, ap = sum(b in ACTION for _, b in pairs), sum(a in ACTION for a, _ in pairs)
    bp, br = (tp / pp if pp else None), (tp / ap if ap else None)
    return {"n": n, "accuracy": round(acc, 4), "macro_f1": round(sum(macro) / len(macro), 4) if macro else None,
            "kappa": None if kappa is None else round(kappa, 4), "per_class": per,
            "confusion": {f"{a}→{b}": k for (a, b), k in sorted(Counter(pairs).items())},
            "binary_actionable": {"precision": None if bp is None else round(bp, 4), "recall": None if br is None else round(br, 4),
                                  "f1": None if f1(bp, br) is None else round(f1(bp, br), 4)}}


def main() -> None:
    all_pairs, events, totals = [], {}, Counter()
    for path in sorted(LABELS.glob("*.json")):
        eid = path.stem
        labels = {x["clause_id"]: x["verdict"] for x in json.loads(path.read_text(encoding="utf-8"))["labels"]}
        brief = json.loads((BRIEFS / f"{eid}.json").read_text(encoding="utf-8"))["briefing"]
        agent = {j["clause_id"]: j["verdict"] for f in brief["match"]["doc_fits"] for j in f["judgments"]}
        uncertain = [c for c, v in agent.items() if v == "uncertain"]
        pairs = [(labels[c], v) for c, v in agent.items() if v != "uncertain" and c in labels]
        missed = [c for c, v in labels.items() if v == "applicable" and c not in agent]
        events[eid] = {"labels": dict(Counter(labels.values())), "judged": len(agent), "coverage": round(len(agent) / len(labels), 4),
                       "uncertain": len(uncertain), "missed_applicable": missed, **scores(pairs)}
        all_pairs += pairs
        totals.update(judged=len(agent), labels=len(labels), uncertain=len(uncertain), missed=len(missed),
                      label_applicable=sum(v == "applicable" for v in labels.values()))
    out = {"generated_at": date.today().isoformat(), "preregistration": "data/backtest/ablation/preregistration_v7_clause_labels.json",
           "overall": {"coverage": round(totals["judged"] / totals["labels"], 4), "uncertain": totals["uncertain"],
                       "missed_applicable": totals["missed"], "label_applicable": totals["label_applicable"], **scores(all_pairs)},
           "events": events}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    o = out["overall"]
    print(json.dumps({k: o[k] for k in ("coverage", "n", "accuracy", "macro_f1", "kappa", "binary_actionable",
                                         "uncertain", "missed_applicable", "label_applicable")}, ensure_ascii=False))
    for eid, e in events.items():
        print(eid, "판정", e["judged"], "정확도", e.get("accuracy"), "kappa", e.get("kappa"), "누락", len(e["missed_applicable"]))


if __name__ == "__main__":
    main()
