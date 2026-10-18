"""자금 흐름 데이터 품질 보고서 (사전 등록 v2 기준) → data/backtest/flow_quality.json.

사건 적중 성적은 보지 않고 데이터 자체의 품질만 본다. 최종 제외 여부는 사용자가 결정한다.
사용: python -m scripts.run_flow_quality
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.backtest import flow_series_active, flow_zscores
from app.config import ROOT_DIR, load_config
from app.corpus import load_events
from app.services import market_panel

OUT = ROOT_DIR / "data" / "backtest" / "flow_quality.json"
NOMINAL_DAYS = 7  # 주간 시리즈


def main() -> None:
    cfg = load_config()["sentinel"]["flow"]
    rc = load_config()["backtest"]["random_calm"]
    panel = market_panel()
    events = load_events()
    days = pd.bdate_range(rc["start"], rc["end"])
    near = np.zeros(len(days), dtype=bool)
    for e in events:
        near |= np.abs((days - pd.Timestamp(e.date)).days) <= rc["exclude_days"]
    calm_days = days[~near]
    active = flow_series_active(panel, calm_days)

    rows = []
    for sid in cfg["series"]:
        s = panel[sid]
        z = flow_zscores(s, cfg).dropna()
        lag = cfg["publication_lag_days"][sid]
        first_usable = (z.index[0] + pd.Timedelta(days=lag)).date() if len(z) else None
        last_obs = s.index[-1].date()
        uncovered = [e.id for e in events if first_usable is None or e.date < first_usable
                     or pd.Timestamp(e.date) > s.index[-1] + pd.Timedelta(days=lag + 14)]
        max_gap = int(s.index.to_series().diff().dt.days.max())
        calm_rate = round(float(active[sid].mean()), 4) if sid in active else None
        reasons = []
        if len(uncovered) >= 3:
            reasons.append(f"관측 범위 밖 사건 {len(uncovered)}개")
        if calm_rate is not None and calm_rate > 0.10:
            reasons.append(f"평상 구간 발동률 {calm_rate:.1%} > 10%")
        if max_gap > 3 * NOMINAL_DAYS:
            reasons.append(f"최대 관측 공백 {max_gap}일 > {3 * NOMINAL_DAYS}일")
        rows.append({"series": sid, "first_obs": s.index[0].date().isoformat(), "last_obs": last_obs.isoformat(),
                     "first_usable": first_usable.isoformat() if first_usable else None,
                     "publication_lag_days": lag, "max_gap_days": max_gap, "discontinued": (pd.Timestamp.today() - s.index[-1]).days > 120,
                     "events_out_of_range": uncovered, "calm_active_rate": calm_rate,
                     "exclude_recommended": bool(reasons), "reasons": reasons})
    korea = {"series": "KRX 외국인 순매수 (코스피, 일간)", "status": "미수집",
             "reason": "KRX 정보데이터시스템이 로그인 필요(응답 LOGOUT)로 바뀜. KRX Open API 또는 한국은행 ECOS 무료 인증키 필요"}
    out = {"preregistration": "data/backtest/ablation/preregistration_v2.json", "calm_days": len(calm_days),
           "series": rows, "korea": korea,
           "combined_calm_active_rate": round(float(active.any(axis=1).mean()), 4) if not active.empty else None}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for r in rows:
        flag = "제외 권고" if r["exclude_recommended"] else "유지"
        print(f"{r['series']:15s} {r['first_obs']}~{r['last_obs']}  시차 {r['publication_lag_days']:2d}일  최대공백 {r['max_gap_days']:3d}일  "
              f"평상발동률 {r['calm_active_rate']:.2%}  범위밖 {r['events_out_of_range']}  → {flag} {r['reasons']}")
    print(f"C 전체(하나라도) 평상 발동률: {out['combined_calm_active_rate']:.2%}")


if __name__ == "__main__":
    main()
