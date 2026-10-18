"""P8 백테스트 지표 산출 → data/backtest_results.json.

입력: data/backtest/briefings/*.json (scripts.run_replay 결과), data/backtest/sentinel_results.json,
      data/labels/*.json (작성된 라벨만). 실제 실행값만 기록하고, 라벨이 없는 지표는 null.
사용: python -m scripts.run_backtest
"""

from __future__ import annotations

import json
from datetime import date

from app.backtest import event_metrics, mean_or_none, random_calm
from app.config import ROOT_DIR, load_config
from app.corpus import load_events, load_labels
from app.schemas import Briefing
from app.services import market_panel

BT = ROOT_DIR / "data" / "backtest"
OUT = ROOT_DIR / "data" / "backtest_results.json"


def main() -> None:
    labels = {lb.event_id: lb for lb in load_labels()}
    sentinel = json.loads((BT / "sentinel_results.json").read_text(encoding="utf-8"))
    first_alert = {r["event_id"]: r["first_alert"] for r in sentinel["events"]}

    rows = []
    for e in sorted(load_events(), key=lambda e: e.date):
        b = Briefing.model_validate(json.loads((BT / "briefings" / f"{e.id}.json").read_text(encoding="utf-8"))["briefing"])
        fa = first_alert.get(e.id)
        rows.append(event_metrics(b, labels.get(e.id), date.fromisoformat(fa) if fa else None))

    cfg = load_config()["backtest"]["random_calm"]
    rc = random_calm(market_panel(), [e.date for e in load_events()], cfg["seed"], cfg["n_quarters"],
                     cfg["exclude_days"], cfg["start"], cfg["end"])

    metric_keys = ["lead_time", "doc_top3_hit", "clause_precision", "clause_recall", "gap_precision", "gap_recall", "path_recall"]
    out = {
        "generated_at": date.today().isoformat(),
        "labeled_events": sorted(labels),
        "unlabeled_events": sorted({e.id for e in load_events()} - set(labels)),
        "summary": {k: mean_or_none([r[k] for r in rows]) for k in metric_keys}
        | {"alerts_reproduced": sum(r["first_alert"] is not None for r in rows), "n_events": len(rows),
           "false_alarms_calm_alert": sum(c["alert_days"] for c in sentinel["calm"]),
           "random_calm_market_active_rate": rc.active_rate, "learner_delta": None},
        "events": rows,
        "false_alarms": {
            "calm_windows": sentinel["calm"],
            "random_calm": {"n_days": rc.n_days, "market_active_rate": rc.active_rate, "quarters": rc.quarters,
                            "note": "백테스트 시그널 B(사건 카드)가 없는 구간이라 ALERT는 구조적으로 0. 시그널 A 단독 발동(WATCH)률을 오경보 대리 지표로 기록."},
        },
        "notes": [
            "라벨은 사용자가 직접 설계한 합성 라벨이다.",
            "gap_precision/recall: 예측·정답 공백이 모두 없으면 1.0으로 계산.",
            "path_recall은 gfc_2008(보유내역 없음)에서 계산하지 않는다.",
            "learner_delta는 P9에서 산출.",
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))
    print("라벨 미작성:", ", ".join(out["unlabeled_events"]) or "없음")
    print(f"무작위 평상 구간: 영업일 {rc.n_days}일 중 시그널 A 발동률 {rc.active_rate:.2%}")
    for q in rc.quarters:
        print(f"  {q['quarter']}: {q['market_active_days']}/{q['days']}일")


if __name__ == "__main__":
    main()
