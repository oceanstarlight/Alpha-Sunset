"""로컬(대한민국) Sentinel — 사전 등록 v5.

A_kr 시장(ECOS 일별) · C_kr 외국인 순매수 · B_kr 뉴스 급증 · DART 신용 공시 경고 · 해외-한국 연관성 근거.
모든 판단은 원인-근거-결과(chain)로 남긴다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.agents import sentinel
from app.agents.sentinel import AlertLevel, MarketSignal, latest_zscore
from app.config import load_config
from app.data.korea import Disclosure, NewsItem

RULE = "사전 등록 v5"
KR_LABEL = {
    "KOSPI": "코스피", "USDKRW": "원/달러", "KTB3Y": "국고채 3년", "CREDIT_KR": "회사채AA−국고채 3년 금리차",
    "CD91": "CD 91일", "FOREIGN_NET_KOSPI": "코스피 외국인 순매수", "FOREIGN_NET_5D": "외국인 순매수 5일 누적",
    "CREDIT_GLOBAL": "미 신용스프레드(HY·Baa)",
}


def _cfg() -> dict[str, Any]:
    return load_config()["korea"]


def _label(sid: str) -> str:
    return KR_LABEL.get(sid) or sentinel.SERIES_LABEL.get(sid, sid)


# ---------- A_kr 시장 ----------


def kr_panel(raw: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """ECOS 원시 시리즈 → 신호용 패널 (파생: 신용 스프레드)."""
    panel = dict(raw)
    for name, (a, b) in _cfg()["market"]["derived"].items():
        if a in raw and b in raw:
            panel[name] = (raw[a] - raw[b]).dropna()
    return panel


def _kr_market_cfg() -> dict[str, Any]:
    """임계치는 글로벌 시그널 A와 같은 값 (v5 원칙), 변화 방식만 시리즈별."""
    base = dict(load_config()["sentinel"]["market"])
    series = _cfg()["market"]["series"]
    base["diff_series"] = [s for s, c in series.items() if c["change"] == "diff"] + list(_cfg()["market"]["derived"])
    return base


def kr_market_signal(panel: dict[str, pd.Series], as_of: date) -> MarketSignal:
    cfg = _kr_market_cfg()
    view = sentinel.AsOfPanel(panel, as_of=as_of)
    zscores = {}
    for sid in _cfg()["market"]["signal_series"]:
        z = latest_zscore(view.series(sid, as_of), sid, as_of, cfg)
        if z is not None:
            zscores[sid] = z
    triggered = [s for s, z in zscores.items() if abs(z) >= cfg["z_threshold"]]
    active = len(triggered) >= cfg["min_series"] or any(abs(z) >= cfg["z_extreme"] for z in zscores.values())
    return MarketSignal(as_of=as_of, zscores=zscores, triggered=triggered, active=active)


# ---------- C_kr 외국인 순매수 ----------


def kr_flow_signal(panel: dict[str, pd.Series], as_of: date) -> sentinel.FlowSignal | None:
    """순매수는 수준 자체가 흐름이므로 수준 z-score (시그널 C와 같은 규칙). 데이터 없으면 None."""
    fcfg, gcfg = _cfg()["flow"], load_config()["sentinel"]["flow"]
    s = panel.get("FOREIGN_NET_KOSPI")
    if s is None:
        return None
    s = s.loc[: pd.Timestamp(as_of)]
    zscores = {}
    for sid, x in (("FOREIGN_NET_KOSPI", s), ("FOREIGN_NET_5D", s.rolling(fcfg["cumulative_days"]).sum().dropna())):
        hist = x.iloc[-(gcfg["lookback_obs"] + 1): -1]
        if len(hist) >= gcfg["min_obs"] and hist.std():
            zscores[sid] = float((x.iloc[-1] - hist.mean()) / hist.std())
    triggered = [k for k, z in zscores.items() if abs(z) >= gcfg["z_threshold"]]
    return sentinel.FlowSignal(as_of=as_of, zscores=zscores, triggered=triggered, active=bool(triggered))


# ---------- B_kr 뉴스 급증 ----------


@dataclass
class KrNewsCluster:
    event_type: str
    n_articles: int
    n_sources: int
    z: float
    top_titles: list[str]


@dataclass
class KrNewsSignal:
    as_of: datetime
    clusters: list[KrNewsCluster] = field(default_factory=list)
    observations: dict[str, dict] = field(default_factory=dict)  # 주제별 기사 수·언론사 수·z·기준점 수
    notes: list[str] = field(default_factory=list)  # 미설정·실패·기준선 축적 중

    @property
    def active(self) -> bool:
        return bool(self.clusters)

    @property
    def status(self) -> str:
        obs = self.observations.values()
        if not obs or all(o.get("z") is None for o in obs):
            return "unavailable"
        return "partial" if any(o.get("z") is None for o in obs) else "ok"


def baseline_z(history: list[dict], event_type: str, now: datetime, count: int,
               cfg: dict | None = None, field: str = "n_articles") -> tuple[float | None, int]:
    """직전 baseline_days일 같은 시간대(±baseline_window_min분, 기본 60) 기사 수 대비 z. 기준점 부족이면 (None, 개수)."""
    cfg = cfg or _cfg()["news"]
    window = cfg.get("baseline_window_min", 60)
    start = now - timedelta(days=cfg["baseline_days"])
    pts = []
    for h in history:
        ts = datetime.fromisoformat(h["ts"])
        if h["event_type"] != event_type or h.get(field) is None or not (start <= ts < now - timedelta(hours=1)):
            continue
        minutes = abs((ts.hour * 60 + ts.minute) - (now.hour * 60 + now.minute))
        if min(minutes, 1440 - minutes) <= window:
            pts.append(h[field])
    if len(pts) < cfg["baseline_min_points"]:
        return None, len(pts)
    std = float(np.std(pts, ddof=1))
    return (float((count - np.mean(pts)) / std) if std else None), len(pts)


def kr_news_signal(articles: dict[str, list[NewsItem]], history: list[dict], now: datetime,
                   notes: list[str] | None = None) -> tuple[KrNewsSignal, list[dict]]:
    """주제별 기사 → 신호. 반환: (신호, 이번 관측(history에 추가할 행))."""
    cfg = _cfg()["news"]
    sig = KrNewsSignal(as_of=now, notes=list(notes or []))
    new_rows = []
    for event_type, items in articles.items():
        n, sources = len(items), len({i.source for i in items})
        z, n_base = baseline_z(history, event_type, now, n)
        sig.observations[event_type] = {"n_articles": n, "n_sources": sources, "z": z, "baseline_points": n_base}
        new_rows.append({"ts": now.isoformat(), "event_type": event_type, "n_articles": n, "n_sources": sources})
        if z is None:
            sig.notes.append(f"{event_type}: 기준선 축적 중 ({n_base}/{cfg['baseline_min_points']})")
            continue
        if z >= cfg["z_threshold"] and sources >= cfg["min_sources"]:
            top = [i.title for i in sorted(items, key=lambda i: i.published, reverse=True)[:3]]
            sig.clusters.append(KrNewsCluster(event_type, n, sources, z, top))
    return sig, new_rows


# ---------- DART 신용 공시 경고 ----------


@dataclass
class DartWarning:
    disclosure: Disclosure
    keyword: str
    confirmed: bool = False
    n_sources: int = 0  # 기업명 기사 언론사 수 (승격 판정용)


def dart_warnings(disclosures: list[Disclosure]) -> list[DartWarning]:
    cfg = _cfg()["dart"]
    out = []
    for d in disclosures:
        if d.corp_cls not in cfg["listed_classes"]:
            continue
        kw = next((k for k in cfg["report_keywords"] if k in d.report_nm.replace(" ", "")), None)
        if kw:
            out.append(DartWarning(d, kw))
    return out


def confirm_warning(w: DartWarning, corp_articles: list[NewsItem], now: datetime) -> DartWarning:
    """공시 후 confirm_hours 안에 기업명 기사가 언론사 min_sources곳 이상이면 사건 확정 (v5 Q3)."""
    cfg = _cfg()
    start = datetime.combine(w.disclosure.rcept_dt, datetime.min.time(), tzinfo=now.tzinfo)
    deadline = start + timedelta(hours=cfg["dart"]["confirm_hours"])
    relevant = [a for a in corp_articles if w.disclosure.corp_name in a.title and start <= a.published <= deadline]
    w.n_sources = len({a.source for a in relevant})
    w.confirmed = w.n_sources >= cfg["news"]["min_sources"]
    return w


# ---------- 해외-한국 연관성 근거 ----------


def _changes(s: pd.Series, sid: str) -> pd.Series:
    diff_ids = set(load_config()["sentinel"]["market"]["diff_series"]) | set(_kr_market_cfg()["diff_series"]) | {"CREDIT_GLOBAL"}
    return (s.diff() if sid in diff_ids else s.pct_change()).dropna()


def global_credit(panel: dict[str, pd.Series]) -> pd.Series | None:
    cs = load_config()["sentinel"]["market"]["credit_spread"]
    for sid in (cs["primary"], cs["fallback"]):
        if sid in panel and len(panel[sid]) > 300:
            return panel[sid]
    return None


def historical_link(global_panel: dict[str, pd.Series], kr: dict[str, pd.Series], as_of: date, lag: int | None = None) -> list[dict]:
    """쌍별 기준일 전날까지 window 영업일 일변화 상관과 최근 history_years년 분위수 (미래 데이터 미사용).

    v5.1: 해외 t−lag 변화 ↔ 한국 t 변화 (미국 장은 한국 장 마감 뒤에 열린다). lag=0이면 v5(같은 날).
    """
    lag = _cfg()["linkage"]["lag"] if lag is None else lag
    cfg = _cfg()["linkage"]
    g = dict(global_panel)
    credit = global_credit(global_panel)
    if credit is not None:
        g["CREDIT_GLOBAL"] = credit
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=1)
    out = []
    for gid, kid in cfg["pairs"]:
        if gid not in g or kid not in kr:
            out.append({"pair": f"{_label(gid)} ↔ {_label(kid)}", "corr": None, "percentile": None, "n": 0, "note": "데이터 없음"})
            continue
        df = pd.concat([_changes(g[gid], gid), _changes(kr[kid], kid)], axis=1, join="outer")
        df.iloc[:, 0] = df.iloc[:, 0].ffill(limit=3).shift(lag)  # 해외 직전 관측을 한국 다음 거래일에 맞춘다
        df = df.dropna(subset=[df.columns[1]]).loc[:cutoff].dropna()
        if len(df) < cfg["window"]:
            out.append({"pair": f"{_label(gid)} ↔ {_label(kid)}", "corr": None, "percentile": None, "n": len(df), "note": "관측 부족"})
            continue
        roll = df.iloc[:, 0].rolling(cfg["window"]).corr(df.iloc[:, 1]).dropna()
        recent = roll.loc[roll.index[-1] - pd.DateOffset(years=cfg["history_years"]):]
        cur = float(roll.iloc[-1])
        out.append({"pair": f"{_label(gid)} ↔ {_label(kid)}", "corr": round(cur, 3),
                    "percentile": round(float((recent.abs() <= abs(cur)).mean() * 100), 1), "n": cfg["window"], "note": ""})
    return out


def linkage_evidence(global_market: MarketSignal, kr_market: MarketSignal, links: list[dict],
                     kr_exposure: float | None = None, kr_impact: float | None = None,
                     global_prev: MarketSignal | None = None) -> dict:
    """대응안에 붙일 연관성 근거 (v5: 해외 사건으로 로컬 대응안이 나갈 때 필수 첨부)."""
    weak = _cfg()["linkage"]["weak_abs_corr"]
    corrs = [abs(x["corr"]) for x in links if x["corr"] is not None]
    return {
        "co_movement": {"global": {**({f"{k}(t-1)": round(global_prev.zscores[k], 2) for k in global_prev.triggered} if global_prev else {}),
                                   **{k: round(global_market.zscores[k], 2) for k in global_market.triggered}},
                        "korea": {k: round(kr_market.zscores[k], 2) for k in kr_market.triggered}},
        "historical_link": links,
        "exposure_link": {"kr_weight": kr_exposure, "kr_impact": kr_impact},
        "weak": not corrs or max(corrs) < weak,
        "caveat": "상관은 인과가 아니다. 판단 보조 근거이며 최종 결정은 사람이 한다.",
    }


# ---------- 등급 · 원인-근거-결과 ----------


@dataclass
class LocalResult:
    as_of: datetime
    level: AlertLevel
    kr_market: MarketSignal | None
    kr_flow: sentinel.FlowSignal | None
    kr_news: KrNewsSignal | None
    global_news_active: bool
    warnings: list[DartWarning] = field(default_factory=list)
    linkage: dict | None = None

    @property
    def money_alert(self) -> bool:
        return bool((self.kr_market and self.kr_market.active) or (self.kr_flow and self.kr_flow.active))

    @property
    def event_confirmed(self) -> bool:
        return bool((self.kr_news and self.kr_news.active) or self.global_news_active or any(w.confirmed for w in self.warnings))


def local_grade(kr_market: MarketSignal | None, kr_flow, kr_news: KrNewsSignal | None, global_news_active: bool,
                warnings: list[DartWarning]) -> AlertLevel:
    """로컬 ALERT = B_any ∧ (A_kr ∨ C_kr). B_any = 한국 뉴스 군집 ∨ 글로벌 사건 ∨ 확정된 DART 경고."""
    money = bool((kr_market and kr_market.active) or (kr_flow and kr_flow.active))
    event = bool((kr_news and kr_news.active) or global_news_active or any(w.confirmed for w in warnings))
    if money and event:
        return AlertLevel.ALERT
    if money or event or warnings:
        return AlertLevel.WATCH
    return AlertLevel.NONE


def _z(z: dict[str, float], ids) -> str:
    return ", ".join(f"{_label(s)} z={z[s]:+.2f}" for s in ids)


def explain_local(r: LocalResult) -> list[dict[str, str]]:
    cfg, mcfg = _cfg(), load_config()["sentinel"]["market"]
    chain = []
    if r.kr_market is None:
        chain.append({"단계": "한국 시장(A_kr)", "원인": "데이터 없음", "근거": "ECOS 키 미설정 또는 조회 실패", "결과": "판단 불가"})
    else:
        m = r.kr_market
        chain.append({"단계": "한국 시장(A_kr)",
                      "원인": _z(m.zscores, m.triggered) or "임계 초과 지표 없음",
                      "근거": f"ECOS 일별 1일 변화 z (기준일 {m.as_of}), 규칙 |z| ≥ {mcfg['z_threshold']} 지표 {mcfg['min_series']}개 이상 "
                              f"또는 |z| ≥ {mcfg['z_extreme']} ({RULE}). 관측: {_z(m.zscores, m.zscores) or '-'}",
                      "결과": "활성" if m.active else "비활성"})
    if r.kr_flow is not None:
        f = r.kr_flow
        chain.append({"단계": "외국인 자금(C_kr)", "원인": _z(f.zscores, f.triggered) or "임계 초과 없음",
                      "근거": f"외국인 순매수 수준 z, 규칙 |z| ≥ {load_config()['sentinel']['flow']['z_threshold']} ({RULE})",
                      "결과": "활성" if f.active else "비활성"})
    if r.kr_news is not None:
        n = r.kr_news
        if n.clusters:
            cause = "; ".join(f"{c.event_type}: {c.top_titles[0] if c.top_titles else ''}" for c in n.clusters)
            ev = "; ".join(f"{c.event_type}: 기사 {c.n_articles}건 · 언론사 {c.n_sources}곳 · z={c.z:.1f}" for c in n.clusters)
        else:
            cause = "급증 군집 없음" if n.status != "unavailable" else "판단 불가 (" + "; ".join(n.notes[:3]) + ")"
            ev = ""
        ev += f" 규칙: 최근 {cfg['news']['window_hours']}시간 기사 수 z ≥ {cfg['news']['z_threshold']} (직전 {cfg['news']['baseline_days']}일 같은 시간대) " \
              f"AND 언론사 ≥ {cfg['news']['min_sources']}곳 ({RULE}). 출처: Google 뉴스 RSS"
        chain.append({"단계": "한국 사건(B_kr)", "원인": cause, "근거": ev.strip(),
                      "결과": {"ok": "활성" if n.active else "비활성", "partial": ("활성" if n.active else "비활성") + " (일부 판단 불가)",
                             "unavailable": "판단 불가"}[n.status]})
    for w in r.warnings:
        d = w.disclosure
        chain.append({"단계": "DART 신용 공시",
                      "원인": f"{d.corp_name}({d.stock_code}) {d.report_nm} ({d.rcept_dt})",
                      "근거": f"공시 원문 {d.url} · 키워드 '{w.keyword}' · 기업명 기사 언론사 {w.n_sources}곳 "
                              f"(확정 기준 {cfg['dart']['confirm_hours']}시간 내 {cfg['news']['min_sources']}곳, {RULE})",
                      "결과": "사건 확정" if w.confirmed else "사건 경고 (대응안 없음, 알림만)"})
    if r.global_news_active and r.linkage:
        lk = r.linkage
        links = "; ".join(f"{x['pair']} ρ={x['corr']} (최근 5년 {x['percentile']}분위, 해외 1일 시차)" for x in lk["historical_link"] if x["corr"] is not None)
        chain.append({"단계": "해외-한국 연관성",
                      "원인": f"해외 사건 신호 활성 · 동시 반응 해외 {lk['co_movement']['global'] or '-'} / 한국 {lk['co_movement']['korea'] or '-'}",
                      "근거": (links or "상관 데이터 없음") + f" · 한국 노출 비중 {lk['exposure_link']['kr_weight']}. {lk['caveat']}",
                      "결과": "연관 근거 약함" if lk["weak"] else "연관 근거 있음"})
    action = {AlertLevel.ALERT: "2단계: 대응안 리포트 생성", AlertLevel.NONE: "조치 없음",
              AlertLevel.WATCH: "1단계: 자금 이상 알림" if r.money_alert else ("사건 경고 알림" if r.warnings or r.event_confirmed else "관찰")}[r.level]
    chain.append({"단계": "로컬 종합 등급",
                  "원인": f"A_kr/C_kr={'활성' if r.money_alert else '비활성'}, 사건(B_any)={'확정' if r.event_confirmed else '미확정'}, "
                          f"DART 경고 {len(r.warnings)}건",
                  "근거": f"로컬 ALERT = (한국 사건 ∨ 해외 사건 ∨ 확정 DART) ∧ (A_kr ∨ C_kr) ({RULE})",
                  "결과": f"{r.level.value} → {action}"})
    return chain


def to_json(r: LocalResult) -> dict:
    return {
        "as_of": r.as_of.isoformat(timespec="minutes"), "level": r.level.value, "money_alert": r.money_alert,
        "event_confirmed": r.event_confirmed,
        "kr_market": asdict(r.kr_market) if r.kr_market else None,
        "kr_flow": asdict(r.kr_flow) if r.kr_flow else None,
        "kr_news": ({"status": r.kr_news.status, "clusters": [asdict(c) for c in r.kr_news.clusters],
                     "observations": r.kr_news.observations, "notes": r.kr_news.notes} if r.kr_news else None),
        "warnings": [{**asdict(w.disclosure), "url": w.disclosure.url, "keyword": w.keyword, "confirmed": w.confirmed,
                      "n_sources": w.n_sources} for w in r.warnings],
        "linkage": r.linkage, "chain": explain_local(r),
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
