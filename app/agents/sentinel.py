"""Sentinel: 시장 신호(A) + 사건 신호(B) 이중 조건 경보 (plans.md 5.1).

- A: FRED 시리즈 1일 변화의 z-score (trailing 252영업일, 당일 제외)
- B: 라이브는 Google 뉴스 RSS 주제별 기사 수 급증 + 언론사 수, 백테스트는 사건 카드(date 이후만 공개)
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


# ---------- 시그널 C (자금 흐름) ----------


@dataclass
class FlowSignal:
    as_of: date
    zscores: dict[str, float]
    triggered: list[str]
    active: bool


def flow_signal(panel: AsOfPanel, as_of: date) -> FlowSignal:
    """공표 시차를 반영해 as_of에 이미 공개된 관측만으로 주간 자금 흐름 변화율의 z-score를 본다."""
    cfg = _sentinel_cfg()["flow"]
    zscores: dict[str, float] = {}
    for sid in cfg["series"]:
        s = panel.series(sid, as_of)
        if s is None:
            continue
        s = s.loc[: pd.Timestamp(as_of) - pd.Timedelta(days=cfg["publication_lag_days"][sid])]
        chg = s.pct_change().replace([float("inf"), float("-inf")], float("nan")).dropna()
        hist = chg.iloc[-(cfg["lookback_obs"] + 1) : -1]
        if len(hist) < cfg["min_obs"] or not hist.std():
            continue
        zscores[sid] = float((chg.iloc[-1] - hist.mean()) / hist.std())
    triggered = [sid for sid, z in zscores.items() if abs(z) >= cfg["z_threshold"]]
    return FlowSignal(as_of=as_of, zscores=zscores, triggered=triggered, active=bool(triggered))


def panel_series_ids() -> list[str]:
    """Sentinel이 쓰는 FRED 시리즈 전체 (시장 + 신용스프레드 + 자금 흐름)."""
    cfg = _sentinel_cfg()
    m = cfg["market"]
    ids = m["series"] + [m["credit_spread"]["primary"], m["credit_spread"]["fallback"]]
    return ids + (cfg["flow"]["series"] if cfg.get("flow", {}).get("enabled") else [])


def flow_enabled() -> bool:
    return bool(_sentinel_cfg().get("flow", {}).get("enabled"))


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
    errors: list[str] = field(default_factory=list)  # 조회 실패·기준선 축적 중인 주제
    n_queries: int = 0  # 조회한 주제 수 (라이브)

    @property
    def active(self) -> bool:
        return bool(self.clusters)

    @property
    def status(self) -> str:
        """ok: 모두 조회 / partial: 일부 실패 / unavailable: 전부 실패 → '사건 없음'이 아니라 '판단 불가'."""
        if not self.n_queries or not self.errors:
            return "ok"
        return "unavailable" if len(self.errors) >= self.n_queries else "partial"


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


def rss_query(query: str) -> str:
    """주제 쿼리('"a" OR "b"')를 Google 뉴스 검색어로 (OR 문법 그대로 지원)."""
    return query.strip("()")


def fetch_rss_topics(rss: Any, now: datetime) -> tuple[dict[str, list], list[str]]:
    """주제별 최근 window_hours 기사 (Google 뉴스 RSS, 키·요청 제한 없음). 반환: (주제→기사, 실패 사유)."""
    cfg = _sentinel_cfg()["news"]
    since = now - timedelta(hours=cfg["window_hours"])
    out, errors = {}, []
    for event_type, query in cfg["queries"].items():
        try:
            out[event_type] = rss.search(rss_query(query), since)
        except Exception as e:
            errors.append(f"{event_type}: Google 뉴스 RSS 실패 ({type(e).__name__})")
    return out, errors


def rss_news_signal(articles: dict[str, list], history: list[dict], now: datetime,
                    fetch_errors: list[str] | None = None) -> tuple[NewsSignal, list[dict], dict]:
    """라이브 B (글로벌): 주제별 최근 24시간 기사 수가 직전 30일 관측 대비 z ≥ 3 AND 언론사 ≥ 20곳.

    기준선은 수집기가 3시간마다 쌓는 data/live/global_news_history.jsonl. 기준점이 부족한 주제는 '판단 불가'.
    반환: (신호, 이번 관측 행, 주제별 관측).
    """
    from app.agents.local import baseline_z

    cfg = _sentinel_cfg()["news"]
    clusters, errors, rows, obs = [], list(fetch_errors or []), [], {}
    for event_type, items in articles.items():
        n, sources = len(items), len({a.source for a in items})
        z, n_base = baseline_z(history, event_type, now, n, cfg)
        obs[event_type] = {"n_articles": n, "n_sources": sources, "z": None if z is None else round(z, 3),
                           "baseline_points": n_base, "top_titles": [a.title for a in items[:3]]}
        rows.append({"ts": now.isoformat(), "event_type": event_type, "n_articles": n, "n_sources": sources})
        if z is None:
            errors.append(f"{event_type}: 기준선 축적 중 ({n_base}/{cfg['baseline_min_points']})")
            continue
        if z >= cfg["z_threshold"] and sources >= cfg["min_sources"]:
            groups = cluster_titles([a.title for a in items], cfg["cluster_jaccard"])
            top = items[groups[0][0]].title if groups else event_type
            clusters.append(NewsCluster(key=" ".join(sorted(_tokens(top))[:5]) or event_type, label=top,
                                        event_type=event_type, n_articles=n, n_sources=sources, z=z))
    return NewsSignal(as_of=now.date(), clusters=clusters, errors=errors, n_queries=len(cfg["queries"])), rows, obs


# ---------- 등급·병합 ----------


@dataclass
class SentinelResult:
    as_of: date
    level: AlertLevel
    market: MarketSignal
    news: NewsSignal
    flow: FlowSignal | None = None

    @property
    def keys(self) -> list[str]:
        return [c.key for c in self.news.clusters] or ["market"]


def grade(market: MarketSignal, news: NewsSignal, flow: FlowSignal | None = None) -> AlertLevel:
    """ALERT = B ∧ (A ∨ C), WATCH = 하나 이상 활성, NONE = 모두 비활성 (사전 등록 v2)."""
    money = market.active or (flow is not None and flow.active)
    if money and news.active:
        return AlertLevel.ALERT
    if money or news.active:
        return AlertLevel.WATCH
    return AlertLevel.NONE


def evaluate(panel: AsOfPanel, news: NewsSignal, as_of: date) -> SentinelResult:
    market = market_signal(panel, as_of)
    flow = flow_signal(panel, as_of) if flow_enabled() else None
    return SentinelResult(as_of=as_of, level=grade(market, news, flow), market=market, news=news, flow=flow)


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


# ---------- 원인-근거-결과 ----------

SERIES_LABEL = {
    "VIXCLS": "VIX(변동성)", "T10Y2Y": "미 장단기 금리차", "DGS10": "미 10년물 금리", "DEXKOUS": "원/달러 환율",
    "DCOILWTICO": "WTI 유가", "DTWEXBGS": "달러 인덱스", "BAMLH0A0HYM2": "미 하이일드 스프레드",
    "BAA10Y": "Baa 회사채 스프레드", "WRMFNS": "개인 MMF 잔액", "DPSACBW027SBOG": "미 은행 예금",
    "WMTSECL1": "해외 공적 미국채 보관", "WRESBAL": "지급준비금",
}


def _z_text(zscores: dict[str, float], ids: list[str]) -> str:
    return ", ".join(f"{SERIES_LABEL.get(s, s)}({s}) z={zscores[s]:+.2f}" for s in ids)


def explain(result: SentinelResult) -> list[dict[str, str]]:
    """경보 판단을 단계별 원인-근거-결과로 풀어 쓴다 (사용자 요구: 모든 판단에 근거 첨부)."""
    cfg = _sentinel_cfg()
    m, f, n = result.market, result.flow, result.news
    chain = []
    top = sorted(m.zscores, key=lambda s: -abs(m.zscores[s]))[:3]
    chain.append({
        "단계": "시장 신호(A)",
        "원인": _z_text(m.zscores, m.triggered) if m.triggered else "임계 초과 지표 없음",
        "근거": f"FRED 1일 변화 z-score (직전 {cfg['market']['lookback_days']}영업일 기준), 규칙: |z| ≥ "
                f"{cfg['market']['z_threshold']} 지표 {cfg['market']['min_series']}개 이상 또는 |z| ≥ {cfg['market']['z_extreme']}. "
                f"상위: {_z_text(m.zscores, top) or '-'}",
        "결과": "활성" if m.active else "비활성",
    })
    if f is not None:
        chain.append({
            "단계": "자금 흐름(C)",
            "원인": _z_text(f.zscores, f.triggered) if f.triggered else "임계 초과 지표 없음",
            "근거": f"FRED 주간 자금 흐름 (공표 시차 반영), 규칙: |z| ≥ {cfg['flow']['z_threshold']} 하나 이상. "
                    f"관측: {_z_text(f.zscores, list(f.zscores)) or '-'}",
            "결과": "활성" if f.active else "비활성",
        })
    if n.clusters:
        cause = "; ".join(c.label for c in n.clusters[:3])
        evidence = "; ".join(
            f"{c.event_type or '-'}: 기사 {c.n_articles}건 · 언론사 {c.n_sources}곳 · 기사 수 z={c.z:.1f} (Google 뉴스)" if c.z is not None
            else f"사건 카드 기준 (백테스트: 카드 날짜부터 {cfg['news']['card_active_days']}일 활성)" for c in n.clusters[:3])
    else:
        cause = "사건 군집 없음" if n.status == "ok" else f"조회 실패 {len(n.errors)}/{n.n_queries}건"
        evidence = f"규칙: 최근 {cfg['news']['window_hours']}시간 기사 수 z ≥ {cfg['news']['z_threshold']} (직전 30일 관측 기준선) AND 언론사 ≥ {cfg['news']['min_sources']}곳, 출처 Google 뉴스 RSS"
    chain.append({"단계": "사건 신호(B)", "원인": cause, "근거": evidence,
                  "결과": {"ok": "활성" if n.active else "비활성", "partial": ("활성" if n.active else "비활성") + " (일부 조회 실패)",
                         "unavailable": "판단 불가"}[n.status]})
    money = m.active or bool(f and f.active)
    action = {AlertLevel.ALERT: "2단계: 대응안(브리핑) 생성", AlertLevel.WATCH:
              "1단계: 자금 이상 알림" if money else "사건 관찰 (시장 반응 대기)", AlertLevel.NONE: "조치 없음"}[result.level]
    chain.append({
        "단계": "종합 등급",
        "원인": f"A={'활성' if m.active else '비활성'}, C={'활성' if f and f.active else '비활성'}, B={'활성' if n.active else '비활성'}",
        "근거": "등급 규칙(사전 등록 v2·v3): ALERT = B ∧ (A ∨ C), WATCH = 하나 이상 활성",
        "결과": f"{result.level.value} → {action}",
    })
    return chain
