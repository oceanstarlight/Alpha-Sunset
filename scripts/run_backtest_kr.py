"""로컬(대한민국) 신호 백테스트 → data/backtest/kr_results.json (사전 등록 v5 지표).

입력: data/ecos/*.csv (scripts/fetch_ecos.py), data/fred/ (글로벌 비교·연관성), 사건 카드.
임계치는 글로벌과 같고 사건 6개 성적으로 조정하지 않는다. 실제 실행값만 기록한다.
사용: python -m scripts.run_backtest_kr
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from app import backtest_kr as bk
from app.agents import local, sentinel
from app.backtest import mean_or_none
from app.config import ROOT_DIR, load_config
from app.corpus import load_events
from app.services import market_panel

OUT = ROOT_DIR / "data" / "backtest" / "kr_results.json"


def main() -> None:
    panel = bk.load_ecos_panel()
    fred = market_panel()
    cfg = load_config()
    card_days = cfg["sentinel"]["news"]["card_active_days"]
    global_bt = json.loads((ROOT_DIR / "data" / "backtest_results.json").read_text(encoding="utf-8"))
    global_rows = {r["event_id"]: r for r in global_bt["events"]}

    rows = []
    for e in sorted(load_events(), key=lambda e: e.date):
        row = {"event_id": e.id, "date": e.date.isoformat(), "kr_in_regions": "KR" in e.regions}
        row |= bk.event_row(panel, e.date, card_days)
        g = global_rows.get(e.id, {})
        row["global_warning_lead_days"] = g.get("warning_lead_days")
        row["global_briefing_delay_days"] = g.get("briefing_delay_days")
        # 해외 사건(지역에 KR 없음)으로 로컬 대응안이 나가는 경우 연관성 근거 첨부 (v5 필수)
        if not row["kr_in_regions"] and row["first_kr_alert"]:
            d = date.fromisoformat(row["first_kr_alert"])
            gm = sentinel.market_signal(sentinel.AsOfPanel(fred, as_of=d), d)
            km = local.kr_market_signal(panel, d)
            links = local.historical_link({k: v.loc[: pd.Timestamp(d)] for k, v in fred.items()},
                                          {k: v.loc[: pd.Timestamp(d)] for k, v in panel.items()}, d)
            try:  # 노출 경로: 사건일 이전 공시 스냅샷 기준 한국 노출 비중·영향도
                from app import geo
                from app.corpus import load_portfolio

                exp = geo.country_exposure(load_portfolio(), e.id).get("KR")
                imp = geo.country_impact(e, load_portfolio(), e.id).get("KR")
            except Exception:
                exp = imp = None
            row["linkage"] = local.linkage_evidence(gm, km, links, kr_exposure=round(exp, 4) if exp else None,
                                                    kr_impact=round(imp, 4) if imp else None)
        rows.append(row)

    rc = cfg["backtest"]["random_calm"]
    calm = bk.calm_rates(panel, [e.date for e in load_events()], rc["start"], rc["end"], rc["exclude_days"])
    n = len(rows)
    summary = {
        "kr_warning_lead_days": mean_or_none([r["kr_warning_lead_days"] for r in rows]),
        "kr_briefing_delay_days": mean_or_none([r["kr_briefing_delay_days"] for r in rows]),
        "kr_events_with_prior_warning": round(sum(r["first_kr_money_alert"] is not None for r in rows) / n, 4),
        "kr_alerts_reproduced": sum(r["first_kr_alert"] is not None for r in rows),
        "n_events": n,
        **calm,
        "global_reference": {k: global_bt["summary"].get(k) for k in
                             ("warning_lead_days", "briefing_delay_days", "events_with_prior_warning",
                              "calm_money_alert_rate", "warning_base_rate_60d")},
    }
    out = {
        "generated_at": date.today().isoformat(),
        "preregistration": "data/backtest/ablation/preregistration_v5_kr.json",
        "data": {sid: {"start": s.index[0].date().isoformat(), "end": s.index[-1].date().isoformat(), "n": int(len(s))}
                 for sid, s in panel.items()},
        "summary": summary,
        "events": rows,
        "notes": [
            "임계치는 글로벌 A·C와 같고 사건 성적으로 조정하지 않았다 (사전 등록 v5).",
            "사건 신호(B)는 사건 카드 기준(사건일부터 14일). 2단계 = 그 기간 중 A_kr ∨ C_kr가 처음 활성인 날.",
            "kr_events_with_prior_warning은 kr_base_rate(평상일 기준 같은 비율)와 비교해야 한다. 차이가 작으면 선행 알림은 우연일 수 있다.",
            "연관성 근거는 지역에 KR이 없는 해외 사건에만 첨부한다. 상관은 인과가 아니다.",
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in rows:
        print(r["event_id"], r["first_kr_money_alert"], r["kr_warning_lead_days"], r["kr_money_alert_cause"],
              "|", r["first_kr_alert"], r["kr_briefing_delay_days"], r["kr_alert_cause"])


if __name__ == "__main__":
    main()
