"""로컬(대한민국) 신호 백테스트 — 사전 등록 v5 지표.

A_kr·C_kr를 영업일별로 벡터 계산하고, 1단계(자금 이상 알림)·2단계(대응안) 시점과 평상시 알림 비율을 낸다.
임계치·창 크기는 글로벌과 같다 (v5 원칙). 사건 신호(B)는 백테스트에서 사건 카드 기준.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.agents import local
from app.backtest import zscore_series
from app.config import ROOT_DIR, load_config

ECOS_DIR = ROOT_DIR / "data" / "ecos"


def load_ecos_panel() -> dict[str, pd.Series]:
    raw = {p.stem: pd.read_csv(p, index_col=0, parse_dates=True).iloc[:, 0] for p in sorted(ECOS_DIR.glob("*.csv"))}
    return local.kr_panel(raw)


def kr_market_z(panel: dict[str, pd.Series], days: pd.DatetimeIndex) -> pd.DataFrame:
    """영업일별·시리즈별 A_kr z (stale 관측은 NaN)."""
    cfg = local._kr_market_cfg()
    out = {}
    for sid in load_config()["korea"]["market"]["signal_series"]:
        if sid not in panel:
            continue
        zs = zscore_series(panel[sid], sid, cfg)
        obs = pd.Series(zs.index, index=zs.index)
        aligned = zs.reindex(days, method="ffill")
        last_obs = obs.reindex(days, method="ffill")
        stale = (days - pd.DatetimeIndex(last_obs)).days > cfg["stale_days"]
        out[sid] = aligned.where(~stale)
    return pd.DataFrame(out, index=days)


def kr_market_active(z: pd.DataFrame) -> pd.Series:
    cfg = local._kr_market_cfg()
    n = (z.abs() >= cfg["z_threshold"]).sum(axis=1)
    return (n >= cfg["min_series"]) | (z.abs() >= cfg["z_extreme"]).any(axis=1)


def kr_flow_z(panel: dict[str, pd.Series], days: pd.DatetimeIndex) -> pd.DataFrame:
    """외국인 순매수 수준 z (당일 제외 직전 lookback_obs 관측 기준) — local.kr_flow_signal과 같은 규칙."""
    gcfg, fcfg = load_config()["sentinel"]["flow"], load_config()["korea"]["flow"]
    s = panel.get("FOREIGN_NET_KOSPI")
    if s is None:
        return pd.DataFrame(index=days)
    out = {}
    for sid, x in (("FOREIGN_NET_KOSPI", s), ("FOREIGN_NET_5D", s.rolling(fcfg["cumulative_days"]).sum().dropna())):
        prior = x.shift(1).rolling(gcfg["lookback_obs"], min_periods=gcfg["min_obs"])
        z = ((x - prior.mean()) / prior.std()).replace([np.inf, -np.inf], np.nan)
        out[sid] = z.reindex(days, method="ffill", limit=5)
    return pd.DataFrame(out, index=days)


def kr_flow_active(z: pd.DataFrame) -> pd.Series:
    if z.empty:
        return pd.Series(False, index=z.index)
    return (z.abs() >= load_config()["sentinel"]["flow"]["z_threshold"]).any(axis=1)


def kr_daily(panel: dict[str, pd.Series], days: pd.DatetimeIndex) -> pd.DataFrame:
    """영업일별 A_kr·C_kr 활성과 1단계 알림(5영업일 중 2일 이상)."""
    pad = pd.bdate_range(days[0] - pd.Timedelta(days=14), days[-1])
    mz, fz = kr_market_z(panel, pad), kr_flow_z(panel, pad)
    df = pd.DataFrame({"A_kr": kr_market_active(mz), "C_kr": kr_flow_active(fz)}, index=pad)
    df["money"] = df["A_kr"] | df["C_kr"]
    df["money_alert"] = df["money"].astype(int).rolling(5, min_periods=5).sum() >= 2
    return df.reindex(days)


def triggered_on(panel: dict[str, pd.Series], day: pd.Timestamp) -> dict[str, float]:
    """그날 임계를 넘은 한국 시리즈와 z (원인 기록용)."""
    days = pd.DatetimeIndex([day])
    z = pd.concat([kr_market_z(panel, pd.bdate_range(day - pd.Timedelta(days=10), day)).iloc[[-1]],
                   kr_flow_z(panel, pd.bdate_range(day - pd.Timedelta(days=10), day)).iloc[[-1]]], axis=1)
    z.index = days
    mcfg, fth = local._kr_market_cfg(), load_config()["sentinel"]["flow"]["z_threshold"]
    out = {}
    for sid, v in z.iloc[0].dropna().items():
        th = fth if sid.startswith("FOREIGN") else mcfg["z_threshold"]
        if abs(v) >= th:
            out[sid] = round(float(v), 2)
    return out


def event_row(panel: dict[str, pd.Series], event_date: date, card_days: int, lookback: int = 60) -> dict:
    ed = pd.Timestamp(event_date)
    pre = kr_daily(panel, pd.bdate_range(ed - pd.Timedelta(days=lookback), ed))
    alerts = pre.index[pre["money_alert"].fillna(False).astype(bool)]
    first_money = alerts[0] if len(alerts) else None
    post = kr_daily(panel, pd.bdate_range(ed, ed + pd.Timedelta(days=card_days)))
    hits = post.index[post["money"].fillna(False).astype(bool)]  # 2단계: 카드 B 활성 기간 ∧ (A_kr ∨ C_kr)
    first_alert = hits[0] if len(hits) else None
    return {
        "first_kr_money_alert": first_money.date().isoformat() if first_money is not None else None,
        "kr_warning_lead_days": (ed - first_money).days if first_money is not None else None,
        "kr_money_alert_cause": triggered_on(panel, first_money) if first_money is not None else {},
        "first_kr_alert": first_alert.date().isoformat() if first_alert is not None else None,
        "kr_briefing_delay_days": (first_alert - ed).days if first_alert is not None else None,
        "kr_alert_cause": triggered_on(panel, first_alert) if first_alert is not None else {},
        "pre_event_money_alert_days": int(len(alerts)),
    }


def calm_rates(panel: dict[str, pd.Series], event_dates: list[date], start: str, end: str, exclude_days: int) -> dict:
    days = pd.bdate_range(start, end)
    near = np.zeros(len(days), dtype=bool)
    for d in event_dates:
        near |= np.abs((days - pd.Timestamp(d)).days) <= exclude_days
    daily = kr_daily(panel, days)
    alerts = daily["money_alert"].fillna(False).astype(bool)
    calm = days[~near]
    hit = [bool(alerts[(alerts.index >= d - pd.Timedelta(days=60)) & (alerts.index <= d)].any()) for d in calm]
    return {"n_calm_days": int(len(calm)),
            "kr_calm_money_alert_rate": round(float(alerts[~near].mean()), 4),
            "kr_calm_market_active_rate": round(float(daily["A_kr"][~near].fillna(False).mean()), 4),
            "kr_calm_flow_active_rate": round(float(daily["C_kr"][~near].fillna(False).mean()), 4),
            "kr_base_rate": round(float(np.mean(hit)), 4)}
