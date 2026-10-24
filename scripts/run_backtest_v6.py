"""사전 등록 v6 실행 → data/backtest/v6_results.json (A1 사건 확대 검증 + A2 임계치 보정).

사용: python -m scripts.run_backtest_v6
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from app import backtest_kr as bk
from app import backtest_v6 as v6
from app.config import ROOT_DIR, load_config
from app.services import market_panel

OUT = ROOT_DIR / "data" / "backtest" / "v6_results.json"
START, SPLIT, END = "1997-01-01", "2015-01-01", "2025-12-31"


def local_params() -> v6.Params:
    """로컬 현행값 (korea.thresholds)."""
    th = load_config()["korea"]["thresholds"]
    return v6.Params(th["market_z"], th["min_series"], th["min_active"], th["flow_z"], th["z_extreme"])


def main() -> None:
    events = v6.load_v6_events()
    days = pd.bdate_range("1995-06-01", END)
    out = {"generated_at": date.today().isoformat(), "preregistration": str(v6.PREREG.relative_to(ROOT_DIR)),
           "period": {"start": START, "split": SPLIT, "end": END}}
    for scope, frames, params in (
        ("global", v6.global_frames(market_panel(), days), v6.current_params()),
        ("local_kr", v6.local_frames(bk.load_ecos_panel(), days), local_params()),
    ):
        mz, fz = frames
        cur = v6.evaluate(v6.alerts(mz, fz, params), events, START, END)
        cal = v6.calibrate(mz, fz, events, START, SPLIT, END, params)
        out[scope] = {"current_full_period": cur, "calibration": cal}
        if cal.get("adopt"):  # 채택한 임계치로 전체 기간 (화면 요약·README 수치)
            ch = cal["chosen"]
            out[scope]["adopted_full_period"] = v6.evaluate(v6.alerts(mz, fz, v6.Params(
                ch["market_z"], ch["min_series"], ch["persistence"], ch["flow_z"], ch["z_extreme"])), events, START, END)
        b = v6._brief(cur)
        print(f"[{scope}] 현행 전체: {json.dumps(b, ensure_ascii=False)}")
        print(f"[{scope}] 보정: 채택={cal['adopt']} ({cal['reason']}) 선택={cal.get('chosen')}")
        if cal.get("test"):
            print(f"   검증 현행 {json.dumps(cal['test']['current'], ensure_ascii=False)}")
            print(f"   검증 선택 {json.dumps(cal['test']['chosen'], ensure_ascii=False)}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
