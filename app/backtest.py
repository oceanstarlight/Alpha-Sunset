"""백테스트 지표 (plans.md 8장). 라벨이 없는 사건의 라벨 기반 지표는 None으로 둔다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.config import load_config
from app.schemas import Briefing, Channel, Label, Verdict


def precision_recall(predicted: set, expected: set) -> tuple[float | None, float | None]:
    """둘 다 비어 있으면 '없음'을 맞힌 것으로 보고 (1, 1)."""
    if not predicted and not expected:
        return 1.0, 1.0
    hit = len(predicted & expected)
    precision = hit / len(predicted) if predicted else None
    recall = hit / len(expected) if expected else None
    return precision, recall


def doc_top3_hit(b: Briefing, label: Label) -> float | None:
    if not label.expected_docs:
        return None
    top3 = {f.doc_id for f in b.match.doc_fits[:3]}
    return sum(d in top3 for d in label.expected_docs) / len(label.expected_docs)


def clause_pr(b: Briefing, label: Label) -> tuple[float | None, float | None]:
    predicted = {j.clause_id for f in b.match.doc_fits for j in f.judgments if j.verdict == Verdict.not_applicable}
    return precision_recall(predicted, set(label.expected_inapplicable_clauses))


def gap_pr(b: Briefing, label: Label) -> tuple[float | None, float | None]:
    return precision_recall(set(b.match.gaps), set(label.expected_gap_channels))


def path_recall(b: Briefing, label: Label) -> float | None:
    if not label.expected_exposure_paths:
        return None
    found = {p.nodes[1] for p in b.exposure_top if len(p.nodes) > 1}
    return sum(n in found for n in label.expected_exposure_paths) / len(label.expected_exposure_paths)


def lead_time(first_alert: date | None, label: Label) -> int | None:
    """reaction_date − 첫 ALERT (일). 양수면 대응 기한보다 먼저 경보."""
    return (label.reaction_date - first_alert).days if first_alert else None


def event_metrics(b: Briefing, label: Label | None, first_alert: date | None) -> dict:
    row = {"event_id": b.event.id, "first_alert": first_alert.isoformat() if first_alert else None,
           "top3": [f.doc_id for f in b.match.doc_fits[:3]], "gaps": [g.value for g in b.match.gaps],
           "exposure_nodes": [p.nodes[1] for p in b.exposure_top if len(p.nodes) > 1], "labeled": label is not None}
    if label is None:
        return row | {k: None for k in ("lead_time", "doc_top3_hit", "clause_precision", "clause_recall",
                                        "gap_precision", "gap_recall", "path_recall")}
    cp, cr = clause_pr(b, label)
    gp, gr = gap_pr(b, label)
    return row | {"lead_time": lead_time(first_alert, label), "doc_top3_hit": doc_top3_hit(b, label),
                  "clause_precision": cp, "clause_recall": cr, "gap_precision": gp, "gap_recall": gr,
                  "path_recall": path_recall(b, label)}


def mean_or_none(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(float(np.mean(vals)), 4) if vals else None


# ---------- 시그널 A 전 구간 계산 (무작위 평상 구간용) ----------


def zscore_series(s: pd.Series, series_id: str, cfg: dict) -> pd.Series:
    """sentinel.latest_zscore를 모든 관측일에 대해 벡터로 계산 (당일 제외 trailing 창)."""
    chg = (s.diff() if series_id in cfg["diff_series"] else s.pct_change()).dropna()
    prior = chg.shift(1).rolling(cfg["lookback_days"], min_periods=cfg["min_history"])
    z = (chg - prior.mean()) / prior.std()
    return z.replace([np.inf, -np.inf], np.nan)


def market_active_days(panel: dict[str, pd.Series], days: pd.DatetimeIndex) -> pd.Series:
    """영업일별 시그널 A 활성 여부 (stale 관측 제외, 신용스프레드는 HY OAS 우선·BAA10Y 대체)."""
    cfg = load_config()["sentinel"]["market"]
    z = {}
    for sid in cfg["series"] + [cfg["credit_spread"]["primary"], cfg["credit_spread"]["fallback"]]:
        if sid not in panel:
            continue
        zs = zscore_series(panel[sid], sid, cfg)
        obs = pd.Series(zs.index, index=zs.index)
        aligned = zs.reindex(days, method="ffill")
        last_obs = obs.reindex(days, method="ffill")
        stale = (days - pd.DatetimeIndex(last_obs)).days > cfg["stale_days"]
        z[sid] = aligned.where(~stale)
    df = pd.DataFrame(z, index=days)
    primary, fallback = cfg["credit_spread"]["primary"], cfg["credit_spread"]["fallback"]
    if primary in df and fallback in df:
        df[fallback] = df[fallback].where(df[primary].isna())
    hits = (df.abs() >= cfg["z_threshold"]).sum(axis=1)
    extreme = (df.abs() >= cfg["z_extreme"]).any(axis=1)
    return (hits >= cfg["min_series"]) | extreme


@dataclass
class RandomCalmResult:
    n_days: int
    active_rate: float
    quarters: list[dict]


def random_calm(panel: dict[str, pd.Series], event_dates: list[date], seed: int, n_quarters: int,
                exclude_days: int, start: str, end: str) -> RandomCalmResult:
    """사건 ±exclude_days를 뺀 영업일 전체의 시그널 A 발동률 + 무작위 분기 표본."""
    days = pd.bdate_range(start, end)
    near = np.zeros(len(days), dtype=bool)
    for d in event_dates:
        near |= np.abs((days - pd.Timestamp(d)).days) <= exclude_days
    calm_days = days[~near]
    active = market_active_days(panel, calm_days)
    quarters = sorted({(d.year, d.quarter) for d in calm_days})
    rng = np.random.default_rng(seed)
    picked = [quarters[i] for i in sorted(rng.choice(len(quarters), size=min(n_quarters, len(quarters)), replace=False))]
    rows = []
    for y, q in picked:
        mask = (calm_days.year == y) & (calm_days.quarter == q)
        rows.append({"quarter": f"{y}Q{q}", "days": int(mask.sum()), "market_active_days": int(active[mask].sum())})
    return RandomCalmResult(n_days=len(calm_days), active_rate=round(float(active.mean()), 4), quarters=rows)
