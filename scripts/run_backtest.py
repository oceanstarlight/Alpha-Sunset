"""P8 백테스트 지표 산출 → data/backtest_results.json.

입력: data/backtest/briefings/*.json (scripts.run_replay 결과), data/backtest/sentinel_results.json,
      data/labels/*.json (작성된 라벨만). 실제 실행값만 기록하고, 라벨이 없는 지표는 null.
사용: python -m scripts.run_backtest
"""

from __future__ import annotations

import json
from datetime import date

from app.backtest import event_metrics, first_money_alert, mean_or_none, money_alert_days, random_calm, reaction_date_flow
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

    panel = market_panel()
    rows = []
    for e in sorted(load_events(), key=lambda e: e.date):
        b = Briefing.model_validate(json.loads((BT / "briefings" / f"{e.id}.json").read_text(encoding="utf-8"))["briefing"])
        fa = first_alert.get(e.id)
        fa_date = date.fromisoformat(fa) if fa else None
        row = event_metrics(b, labels.get(e.id), fa_date)
        rdf = reaction_date_flow(panel, e.date)  # 사전 등록 v2 기계적 대응일
        row["reaction_date_flow"] = rdf.isoformat()
        row["lead_time_flow"] = (rdf - fa_date).days if fa_date else None
        fma = first_money_alert(panel, e.date)  # 사전 등록 v3: 2단계 운영 지표
        row["first_money_alert"] = fma.isoformat() if fma else None
        row["warning_lead_days"] = (e.date - fma).days if fma else None
        row["briefing_delay_days"] = (fa_date - e.date).days if fa_date else None
        rows.append(row)

    cfg = load_config()["backtest"]["random_calm"]
    rc = random_calm(panel, [e.date for e in load_events()], cfg["seed"], cfg["n_quarters"],
                     cfg["exclude_days"], cfg["start"], cfg["end"])
    import numpy as np
    import pandas as pd
    calm = pd.bdate_range(cfg["start"], cfg["end"])
    near = np.zeros(len(calm), dtype=bool)
    for e in load_events():
        near |= np.abs((calm - pd.Timestamp(e.date)).days) <= cfg["exclude_days"]
    alerts = money_alert_days(panel, calm)
    money_alert_rate = round(float(alerts[~near].mean()), 4)
    # 기준선: 평상일 중 '직전 60일 안에 자금 이상 알림이 있었던' 비율 (사건 전 알림이 우연인지 비교용)
    hit = [bool(alerts[(alerts.index >= d - pd.Timedelta(days=60)) & (alerts.index <= d)].any()) for d in calm[~near]]
    warning_base_rate = round(float(np.mean(hit)), 4)
    events_with_warning = sum(r["first_money_alert"] is not None for r in rows) / len(rows)

    metric_keys = ["warning_lead_days", "briefing_delay_days", "lead_time", "lead_time_flow", "doc_top3_hit", "clause_precision", "clause_recall", "gap_precision", "gap_recall", "path_recall"]
    out = {
        "generated_at": date.today().isoformat(),
        "labeled_events": sorted(labels),
        "unlabeled_events": sorted({e.id for e in load_events()} - set(labels)),
        "summary": {k: mean_or_none([r[k] for r in rows]) for k in metric_keys}
        | {"alerts_reproduced": sum(r["first_alert"] is not None for r in rows), "n_events": len(rows),
           "false_alarms_calm_alert": sum(c["alert_days"] for c in sentinel["calm"]),
           "random_calm_market_active_rate": rc.active_rate, "calm_money_alert_rate": money_alert_rate,
           "events_with_prior_warning": round(events_with_warning, 4), "warning_base_rate_60d": warning_base_rate,
           "learner_delta": None},
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
            "lead_time_flow: 사전 등록 v2 기계적 대응일(사건일 60일 전~사건일, 5영업일 중 2일 이상 A 또는 C 활성인 첫 날) − 첫 ALERT. 음수면 자금·시장 이상 신호보다 경보가 늦음.",
            "ablation(공백 탐지) 결과는 data/backtest/ablation/ 참고.",
            "events_with_prior_warning(사건 전 60일 내 알림이 있었던 사건 비율)은 warning_base_rate_60d(평상일 기준 같은 비율)와 비교해야 한다. 차이가 작으면 선행 알림은 우연일 수 있다.",
            "2단계 운영(사전 등록 v3): 1차 지표는 warning_lead_days(사건 확정 전 자금 이상 알림 선행일), briefing_delay_days(사건 확정 → 대응안), calm_money_alert_rate(평상시 알림 비율).",
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
