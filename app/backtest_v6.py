"""사전 등록 v6: 공개 목록 기반 사건 23개로 1단계 자금 이상 알림을 검증하고, 훈련/검증 분리로 임계치를 보정한다.

z-score는 임계치와 무관하므로 한 번만 계산하고, 임계치 조합(grid)마다 활성·알림만 다시 계산한다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app import backtest_kr as bk
from app.backtest import flow_zscores, zscore_series
from app.config import ROOT_DIR, load_config

PREREG = ROOT_DIR / "data" / "backtest" / "ablation" / "preregistration_v6_events.json"


def load_v6_events() -> list[dict]:
    d = json.loads(PREREG.read_text(encoding="utf-8"))["event_selection"]["events"]
    return [{**e, "date": date.fromisoformat(e["date"])} for e in d]


@dataclass(frozen=True)
class Params:
    market_z: float
    min_series: int
    persistence: int  # 끝나는 5영업일 중 활성일 수
    flow_z: float
    z_extreme: float = 4.0


def current_params() -> Params:
    s = load_config()["sentinel"]
    return Params(s["market"]["z_threshold"], s["market"]["min_series"],
                  s.get("money_alert", {}).get("min_active", 2), s["flow"]["z_threshold"], s["market"]["z_extreme"])


# ---------- z 프레임 (임계치와 무관, 한 번 계산) ----------


def global_frames(panel: dict[str, pd.Series], days: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    mcfg, fcfg = load_config()["sentinel"]["market"], load_config()["sentinel"]["flow"]
    z = {}
    for sid in mcfg["series"] + [mcfg["credit_spread"]["primary"], mcfg["credit_spread"]["fallback"]]:
        if sid not in panel:
            continue
        zs = zscore_series(panel[sid], sid, mcfg)
        obs = pd.Series(zs.index, index=zs.index)
        aligned, last_obs = zs.reindex(days, method="ffill"), obs.reindex(days, method="ffill")
        stale = (days - pd.DatetimeIndex(last_obs)).days > mcfg["stale_days"]
        z[sid] = aligned.where(~stale)
    mz = pd.DataFrame(z, index=days)
    p, f = mcfg["credit_spread"]["primary"], mcfg["credit_spread"]["fallback"]
    if p in mz and f in mz:
        mz[f] = mz[f].where(mz[p].isna())
    fz = {}
    for sid in fcfg["series"]:
        if sid in panel:
            zs = flow_zscores(panel[sid], fcfg)
            zs.index = zs.index + pd.Timedelta(days=fcfg["publication_lag_days"][sid])  # 공개 시점으로
            fz[sid] = zs.reindex(days, method="ffill", limit=10)
    return mz, pd.DataFrame(fz, index=days)


def local_frames(panel: dict[str, pd.Series], days: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    return bk.kr_market_z(panel, days), bk.kr_flow_z(panel, days)


def alerts(mz: pd.DataFrame, fz: pd.DataFrame, p: Params) -> pd.Series:
    a = ((mz.abs() >= p.market_z).sum(axis=1) >= p.min_series) | (mz.abs() >= p.z_extreme).any(axis=1)
    c = (fz.abs() >= p.flow_z).any(axis=1) if not fz.empty else pd.Series(False, index=mz.index)
    money = (a | c).astype(int)
    return money.rolling(5, min_periods=5).sum() >= p.persistence


# ---------- 지표 ----------


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X ≥ k), X ~ B(n, p)."""
    return float(sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def evaluate(alert: pd.Series, events: list[dict], start: str, end: str) -> dict:
    days = alert.loc[start:end].index
    al = alert.reindex(days).fillna(False).astype(bool)
    near = np.zeros(len(days), dtype=bool)
    for e in events:
        near |= np.abs((days - pd.Timestamp(e["date"])).days) <= 180
    calm = days[~near]
    idx = al[al].index

    def has(d0, lo, hi):
        return bool(((idx >= d0 + pd.Timedelta(days=lo)) & (idx <= d0 + pd.Timedelta(days=hi))).any())

    rows = []
    for e in events:
        d0 = pd.Timestamp(e["date"])
        if not (pd.Timestamp(start) <= d0 <= pd.Timestamp(end)):
            continue
        pre = idx[(idx >= d0 - pd.Timedelta(days=60)) & (idx <= d0)]
        rows.append({"id": e["id"], "date": e["date"].isoformat(), "caught": has(d0, -60, 14),
                     "prior_warning": len(pre) > 0, "lead_days": int((d0 - pre[0]).days) if len(pre) else None})
    n = len(rows)
    base_caught = float(np.mean([has(d, -60, 14) for d in calm])) if len(calm) else None
    base_prior = float(np.mean([has(d, -60, 0) for d in calm])) if len(calm) else None
    k_c, k_p = sum(r["caught"] for r in rows), sum(r["prior_warning"] for r in rows)
    leads = [r["lead_days"] for r in rows if r["lead_days"] is not None]
    return {
        "n_events": n, "caught": k_c, "caught_rate": round(k_c / n, 4) if n else None,
        "prior_warning": k_p, "prior_rate": round(k_p / n, 4) if n else None,
        "mean_lead_days": round(float(np.mean(leads)), 1) if leads else None,
        "calm_alert_rate": round(float(al.reindex(calm).mean()), 4) if len(calm) else None,
        "base_rate_caught": None if base_caught is None else round(base_caught, 4),
        "base_rate_prior": None if base_prior is None else round(base_prior, 4),
        "p_value_caught": None if base_caught is None else round(binom_tail(k_c, n, base_caught), 4),
        "p_value_prior": None if base_prior is None else round(binom_tail(k_p, n, base_prior), 4),
        "n_calm_days": int(len(calm)), "events": rows,
    }


def calibrate(mz: pd.DataFrame, fz: pd.DataFrame, events: list[dict], start: str, split: str, end: str,
              current: Params) -> dict:
    """훈련 구간 grid 탐색 → 검증 구간 비교 → 채택 규칙 (사전 등록 v6)."""
    grid = json.loads(PREREG.read_text(encoding="utf-8"))["calibration_A2"]["grid"]
    train_end = (pd.Timestamp(split) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    cand = []
    for mzt in grid["market_z_threshold"]:
        for ms in grid["market_min_series"]:
            for per in grid["persistence_min_active_of_5"]:
                for fzt in grid["flow_z_threshold"]:
                    p = Params(mzt, ms, per, fzt, current.z_extreme)
                    m = evaluate(alerts(mz, fz, p), events, start, train_end)
                    if m["calm_alert_rate"] is None or m["calm_alert_rate"] > 0.05:
                        continue
                    dist = abs(mzt - current.market_z) + abs(ms - current.min_series) + abs(per - current.persistence) \
                        + abs(fzt - current.flow_z)
                    cand.append((m["caught_rate"] - m["calm_alert_rate"], -dist, p, m))
    if not cand:
        return {"chosen": None, "adopt": False, "reason": "평상시 알림 5% 이하 조합 없음"}
    cand.sort(key=lambda c: (c[0], c[1]), reverse=True)
    _, _, best, train_best = cand[0]
    cur_train = evaluate(alerts(mz, fz, current), events, start, train_end)
    cur_test = evaluate(alerts(mz, fz, current), events, split, end)
    new_test = evaluate(alerts(mz, fz, best), events, split, end)
    adopt = (new_test["caught"] >= cur_test["caught"] - 1) and (new_test["calm_alert_rate"] < cur_test["calm_alert_rate"])
    return {"chosen": best.__dict__, "current": current.__dict__,
            "train": {"chosen": _brief(train_best), "current": _brief(cur_train)},
            "test": {"chosen": _brief(new_test), "current": _brief(cur_test)},
            "adopt": bool(adopt) and best != current,
            "reason": ("검증 구간에서 포착 감소 ≤ 1개이고 평상시 알림이 줄어 채택" if adopt and best != current else
                       "현행과 같음" if best == current else "검증 구간 채택 조건 불충족 → 현행 유지"),
            "n_candidates": len(cand)}


def _brief(m: dict) -> dict:
    return {k: m[k] for k in ("n_events", "caught", "caught_rate", "prior_rate", "mean_lead_days", "calm_alert_rate",
                              "base_rate_caught", "p_value_caught")}
