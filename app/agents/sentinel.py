"""Sentinel: 시장 신호(A) + 사건 신호(B) 이중 조건 경보 (plans.md 5.1).

- A: FRED 시리즈 1일 변화의 z-score (trailing 252영업일, 당일 제외)
- B: 라이브는 GDELT 기사량 급증 + 출처 수, 백테스트는 사건 카드(date 이후만 공개)
- 등급: A+B = ALERT, 하나만 = WATCH, 없음 = NONE. 같은 군집은 72h 내 1건으로 병합.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from app.config import load_config
from app.schemas import AlertLevel, Event


class FutureDataError(RuntimeError):
    """백테스트 기준일 이후 데이터 접근 (미래 정보 누수)."""


class AsOfPanel:
    """시점 제한이 걸린 시계열 묶음. as_of=None이면 라이브(제한 없음)."""

    def __init__(self, panel: dict[str, pd.Series], as_of: date | None = None):
        self._panel = panel
        self.as_of = as_of

    def series(self, series_id: str, upto: date) -> pd.Series | None:
        if self.as_of is not None and upto > self.as_of:
            raise FutureDataError(f"{series_id}: 기준일 {self.as_of} 이후({upto}) 데이터 요청")
        s = self._panel.get(series_id)
        return None if s is None else s.loc[: pd.Timestamp(upto)]


# ---------- 시그널 A ----------


@dataclass
class MarketSignal:
    as_of: date
    zscores: dict[str, float]
    triggered: list[str]
    active: bool


def _sentinel_cfg() -> dict[str, Any]:
    return load_config()["sentinel"]


def latest_zscore(s: pd.Series | None, series_id: str, as_of: date, cfg: dict[str, Any]) -> float | None:
    """as_of까지의 데이터로 마지막 1일 변화의 z-score. 데이터 부족·지연 시 None."""
    if s is None or len(s) < cfg["min_history"] + 2:
        return None
    if (pd.Timestamp(as_of) - s.index[-1]).days > cfg["stale_days"]:
        return None
    chg = (s.diff() if series_id in cfg["diff_series"] else s.pct_change()).dropna()
    hist = chg.iloc[-(cfg["lookback_days"] + 1) : -1]
    if len(hist) < cfg["min_history"]:
        return None
    std = hist.std()
    if not std or pd.isna(std):
        return None
    return float((chg.iloc[-1] - hist.mean()) / std)


def market_signal(panel: AsOfPanel, as_of: date) -> MarketSignal:
    cfg = _sentinel_cfg()["market"]
    zscores: dict[str, float] = {}
    for sid in cfg["series"]:
        z = latest_zscore(panel.series(sid, as_of), sid, as_of, cfg)
        if z is not None:
            zscores[sid] = z
    # 신용스프레드: HY OAS 이력이 충분하면 우선, 아니면 BAA10Y
    for sid in (cfg["credit_spread"]["primary"], cfg["credit_spread"]["fallback"]):
        z = latest_zscore(panel.series(sid, as_of), sid, as_of, cfg)
        if z is not None:
            zscores[sid] = z
            break

    triggered = [sid for sid, z in zscores.items() if abs(z) >= cfg["z_threshold"]]
    extreme = any(abs(z) >= cfg["z_extreme"] for z in zscores.values())
    active = len(triggered) >= cfg["min_series"] or extreme
    return MarketSignal(as_of=as_of, zscores=zscores, triggered=triggered, active=active)


# ---------- 시그널 B ----------


@dataclass
class NewsCluster:
    key: str  # 병합 기준 (백테스트: 사건 id, 라이브: 대표 제목 토큰)
    label: str
    event_type: str | None = None
    n_articles: int = 0
    n_sources: int = 0
    z: float | None = None


@dataclass
class NewsSignal:
    as_of: date
    clusters: list[NewsCluster] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # 조회 실패한 쿼리 (예: GDELT 요청 제한)

    @property
    def active(self) -> bool:
        return bool(self.clusters)


def card_news_signal(events: list[Event], as_of: date) -> NewsSignal:
    """백테스트용 B: 사건 카드는 date 당일부터 card_active_days 동안만 '보도됨'으로 본다."""
    days = _sentinel_cfg()["news"]["card_active_days"]
    clusters = [
        NewsCluster(key=e.id, label=e.title, event_type=e.type.value)
        for e in events
        if e.date <= as_of < e.date + timedelta(days=days)
    ]
    return NewsSignal(as_of=as_of, clusters=clusters)


_TOKEN = re.compile(r"[\w가-힣]+")


def _tokens(title: str) -> set[str]:
    return {t for t in _TOKEN.findall(title.lower()) if len(t) > 2}


def cluster_titles(titles: list[str], threshold: float) -> list[list[int]]:
    """제목 토큰 Jaccard 유사도로 탐욕 군집화. 인덱스 묶음을 크기순으로 반환."""
    clusters: list[tuple[set[str], list[int]]] = []
    for i, title in enumerate(titles):
        tok = _tokens(title)
        for rep, members in clusters:
            union = rep | tok
            if union and len(rep & tok) / len(union) >= threshold:
                members.append(i)
                break
        else:
            clusters.append((tok, [i]))
    return sorted((m for _, m in clusters), key=len, reverse=True)


def live_news_signal(client: Any, as_of: date) -> NewsSignal:
    """라이브용 B: 주제 쿼리별 기사량 z ≥ 3 AND 서로 다른 출처 ≥ 20."""
    cfg = _sentinel_cfg()["news"]
    clusters, errors = [], []
    for event_type, query in cfg["queries"].items():
        try:
            vol = client.daily_volume(query).loc[: pd.Timestamp(as_of)]
        except Exception as e:
            errors.append(f"{event_type}: {e}")
            continue
        if len(vol) < cfg["baseline_days"] + 1:
            continue
        base = vol.iloc[-(cfg["baseline_days"] + 1) : -1]
        if not base.std():
            continue
        z = float((vol.iloc[-1] - base.mean()) / base.std())
        if z < cfg["z_threshold"]:
            continue
        try:
            articles = client.articles(query, timespan="1d")
        except Exception as e:
            errors.append(f"{event_type}: {e}")
            continue
        n_sources = len({a.domain for a in articles})
        if n_sources < cfg["min_sources"]:
            continue
        groups = cluster_titles([a.title for a in articles], cfg["cluster_jaccard"])
        top = articles[groups[0][0]].title if groups else event_type
        key = " ".join(sorted(_tokens(top))[:5]) or event_type
        clusters.append(
            NewsCluster(key=key, label=top, event_type=event_type, n_articles=len(articles), n_sources=n_sources, z=z)
        )
    return NewsSignal(as_of=as_of, clusters=clusters, errors=errors)


# ---------- 등급·병합 ----------


@dataclass
class SentinelResult:
    as_of: date
    level: AlertLevel
    market: MarketSignal
    news: NewsSignal

    @property
    def keys(self) -> list[str]:
        return [c.key for c in self.news.clusters] or ["market"]


def grade(market: MarketSignal, news: NewsSignal) -> AlertLevel:
    if market.active and news.active:
        return AlertLevel.ALERT
    if market.active or news.active:
        return AlertLevel.WATCH
    return AlertLevel.NONE


def evaluate(panel: AsOfPanel, news: NewsSignal, as_of: date) -> SentinelResult:
    market = market_signal(panel, as_of)
    return SentinelResult(as_of=as_of, level=grade(market, news), market=market, news=news)


@dataclass
class MergedAlert:
    key: str
    first_seen: datetime
    last_seen: datetime
    count: int = 1


def merge_alerts(results: list[SentinelResult], window_hours: int | None = None) -> list[MergedAlert]:
    """같은 군집 key의 ALERT는 마지막 경보로부터 window_hours 안이면 1건으로 병합한다."""
    window = timedelta(hours=window_hours if window_hours is not None else _sentinel_cfg()["merge_window_hours"])
    merged: list[MergedAlert] = []
    latest: dict[str, MergedAlert] = {}
    for r in sorted(results, key=lambda r: r.as_of):
        if r.level != AlertLevel.ALERT:
            continue
        ts = datetime.combine(r.as_of, time())
        for key in r.keys:
            cur = latest.get(key)
            if cur and ts - cur.last_seen <= window:
                cur.last_seen = ts
                cur.count += 1
            else:
                latest[key] = MergedAlert(key=key, first_seen=ts, last_seen=ts)
                merged.append(latest[key])
    return merged


# ---------- 백테스트 재생 ----------


def replay(panel: dict[str, pd.Series], events: list[Event], start: date, end: date) -> list[SentinelResult]:
    """start~end 영업일마다 그날까지의 정보만으로 평가한다."""
    results = []
    for day in pd.bdate_range(start, end):
        as_of = day.date()
        view = AsOfPanel(panel, as_of=as_of)
        results.append(evaluate(view, card_news_signal(events, as_of), as_of))
    return results
