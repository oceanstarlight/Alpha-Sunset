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
    errors: list[str] = field(default_factory=list)  # 조회 실패한 쿼리 (예: GDELT 요청 제한)
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


def volume_z(vol: pd.Series, baseline_days: int, now: datetime | None = None) -> tuple[float | None, str]:
    """마지막 날 기사량의 z. 오늘(UTC)이 진행 중이면 경과 비율로 하루치를 환산하고, 6시간 미만이면 어제를 쓴다."""
    if len(vol) < baseline_days + 2:
        return None, f"기사량 이력 부족 ({len(vol)}일)"
    now = now or datetime.utcnow()
    last_day = vol.index[-1]
    if last_day.date() == now.date():
        frac = (now - datetime.combine(now.date(), time())).total_seconds() / 86400
        if frac < 0.25:
            vol, note = vol.iloc[:-1], "오늘 6시간 미만 → 어제 기준"
            cur = vol.iloc[-1]
        else:
            cur, note = vol.iloc[-1] / frac, f"오늘 {frac:.0%} 경과분을 하루치로 환산"
    else:
        cur, note = vol.iloc[-1], "마지막 완결일 기준"
    base = vol.iloc[-(baseline_days + 1) : -1]
    if not base.std():
        return None, "기준선 변동 없음"
    return float((cur - base.mean()) / base.std()), note


def news_topic(client: Any, event_type: str, query: str, as_of: date) -> dict:
    """주제 하나의 라이브 B 판정 (요청 1~2회). 조회 실패는 예외로 올린다."""
    cfg = _sentinel_cfg()["news"]
    out = {"event_type": event_type, "z": None, "n_articles": 0, "n_sources": 0, "cluster": None, "note": ""}
    vol = client.daily_volume(query).loc[: pd.Timestamp(as_of)]
    z, out["note"] = volume_z(vol, cfg["baseline_days"])
    if z is None:
        return out
    out["z"] = round(z, 3)
    if z < cfg["z_threshold"]:
        return out
    articles = client.articles(query, timespan="1d")
    n_sources = len({a.domain for a in articles})
    out["n_articles"], out["n_sources"] = len(articles), n_sources
    if n_sources < cfg["min_sources"]:
        return out
    groups = cluster_titles([a.title for a in articles], cfg["cluster_jaccard"])
    top = articles[groups[0][0]].title if groups else event_type
    key = " ".join(sorted(_tokens(top))[:5]) or event_type
    out["cluster"] = NewsCluster(key=key, label=top, event_type=event_type, n_articles=len(articles),
                                 n_sources=n_sources, z=z).__dict__
    return out


def live_news_signal(client: Any, as_of: date) -> NewsSignal:
    """라이브용 B: 주제 쿼리별 기사량 z ≥ 3 AND 서로 다른 출처 ≥ 20."""
    cfg = _sentinel_cfg()["news"]
    clusters, errors = [], []
    for event_type, query in cfg["queries"].items():
        try:
            t = news_topic(client, event_type, query, as_of)
        except Exception as e:
            errors.append(f"{event_type}: {e}")
            continue
        if t["cluster"]:
            clusters.append(NewsCluster(**t["cluster"]))
    return NewsSignal(as_of=as_of, clusters=clusters, errors=errors, n_queries=len(cfg["queries"]))


GDELT_MAX_QUERY = 190  # 실측: 195자 통과, 265자 'too short or too long' 거부 (2026-10-18)


def combined_query(queries: dict[str, str], max_len: int = GDELT_MAX_QUERY) -> str:
    """주제 쿼리들의 키워드를 하나의 OR 쿼리로 (요청 1회). 길이 제한 안에서 주제마다 첫 키워드부터 고르게 담는다."""
    per_topic = [[t.strip() for t in q.strip("()").split(" OR ") if t.strip()] for q in queries.values()]
    chosen: list[str] = []
    for depth in range(max(len(t) for t in per_topic)):
        for terms in per_topic:
            if depth < len(terms) and terms[depth] not in chosen:
                trial = "(" + " OR ".join(chosen + [terms[depth]]) + ")"
                if len(trial) <= max_len:
                    chosen.append(terms[depth])
    return "(" + " OR ".join(chosen) + ")"


def topic_keywords(query: str) -> list[str]:
    return [t.strip().strip('"').lower() for t in query.strip("()").split(" OR ") if t.strip()]


def quick_news_signal(client: Any, as_of: date, rss: Any = None, now: datetime | None = None) -> tuple[NewsSignal, dict]:
    """빠른 조회 (요청 2회): ① GDELT 위기 키워드 OR 쿼리의 일별 기사량 z ② Google 뉴스 RSS(영문) 최근 1일 기사.

    GDELT 기사 목록 요청은 공유 IP에서 429가 잦아 ②는 요청 제한이 없는 RSS로 받는다.
    ②의 제목을 주제 키워드로 나눠, 전체 기사량이 급증(z ≥ 3)했을 때 출처(언론사) ≥ 20곳인 주제를 군집으로 본다.
    주제별 기사량 z는 보지 않는다 (3시간마다 주제별로 나눠 모으는 수집기가 한다).
    """
    cfg = _sentinel_cfg()["news"]
    queries = cfg["queries"]
    q = combined_query(queries)
    errors, z, arts = [], None, []
    z_note = ""
    try:
        vol = client.daily_volume(q).loc[: pd.Timestamp(as_of)]
        z, z_note = volume_z(vol, cfg["baseline_days"])
        if z is None:
            errors.append(f"GDELT 전체 기사량: {z_note}")
    except Exception as e:
        errors.append(f"GDELT 전체 기사량: {e}")
    if rss is None:
        from app.data.korea import GoogleNewsRss

        rss = GoogleNewsRss(lang="en-US", region="US")
    now = now or datetime.now().astimezone()
    try:
        arts = rss.search(q.strip("()"), now - timedelta(days=1))
    except Exception as e:
        errors.append(f"Google 뉴스 RSS: {e}")
    clusters, by_topic = [], {}
    for event_type, tq in queries.items():
        kws = topic_keywords(tq)
        hit = [a for a in arts if any(k in a.title.lower() for k in kws)]
        n_src = len({a.source for a in hit})
        by_topic[event_type] = {"n_articles": len(hit), "n_sources": n_src, "top_titles": [a.title for a in hit[:3]]}
        if z is not None and z >= cfg["z_threshold"] and n_src >= cfg["min_sources"]:
            groups = cluster_titles([a.title for a in hit], cfg["cluster_jaccard"])
            top = hit[groups[0][0]].title if groups else event_type
            clusters.append(NewsCluster(key=" ".join(sorted(_tokens(top))[:5]) or event_type, label=top, event_type=event_type,
                                        n_articles=len(hit), n_sources=n_src, z=z))
    info = {"mode": "quick", "query": q, "combined_z": None if z is None else round(z, 3), "z_note": z_note, "n_articles": len(arts),
            "by_topic": by_topic}
    return NewsSignal(as_of=as_of, clusters=clusters, errors=errors, n_queries=2), info


def news_signal_from_topics(state: dict[str, dict], as_of: date, now: datetime, max_age_hours: float = 26) -> NewsSignal:
    """주제별로 나눠 모은 결과(state)로 B를 만든다. 오래됐거나 한 번도 성공 못 한 주제는 '판단 불가' 사유로 남긴다."""
    queries = _sentinel_cfg()["news"]["queries"]
    clusters, errors = [], []
    for event_type in queries:
        t = state.get(event_type)
        ok_at = datetime.fromisoformat(t["ok_at"]) if t and t.get("ok_at") else None
        if ok_at is None or (now - ok_at).total_seconds() > max_age_hours * 3600:
            last_err = (t or {}).get("error") or "아직 수집 안 됨"
            age = f"마지막 성공 {(now - ok_at).total_seconds() / 3600:.0f}시간 전" if ok_at else "성공 이력 없음"
            errors.append(f"{event_type}: {age} ({last_err})")
            continue
        if t["result"].get("cluster"):
            clusters.append(NewsCluster(**t["result"]["cluster"]))
    return NewsSignal(as_of=as_of, clusters=clusters, errors=errors, n_queries=len(queries))


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
            f"{c.event_type or '-'}: 기사 {c.n_articles}건 · 출처 {c.n_sources}곳 · 기사량 z={c.z:.1f} (GDELT)" if c.z is not None
            else f"사건 카드 기준 (백테스트: 카드 날짜부터 {cfg['news']['card_active_days']}일 활성)" for c in n.clusters[:3])
    else:
        cause = "사건 군집 없음" if n.status == "ok" else f"조회 실패 {len(n.errors)}/{n.n_queries}건"
        evidence = f"규칙: 기사량 z ≥ {cfg['news']['z_threshold']} AND 출처 ≥ {cfg['news']['min_sources']}곳"
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
