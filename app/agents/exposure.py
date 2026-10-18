"""Exposure: 사건 연관 보유 경로 추적 (plans.md 5.3).

그래프: 기관 → (직접 | 위탁운용사 | 카운터파티) → 프록시 펀드 → 보유(발행자 또는 지역별 묶음) → 지역/업종
- relevance(0–1): 사건의 지역·업종·자산군과 노드 속성의 겹침을 규칙으로 계산.
  사건 entities와 보유 발행자는 이름 규칙으로 먼저 매칭하고, 실패한 entity만 LLM이 후보 목록 안에서 매칭.
- risk_score = weight × relevance × (1 − 0.5·uncertainty), 상위 N개 경로 + 경로별 why(LLM, 경로 속성만 입력)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import networkx as nx
import pandas as pd
from pydantic import BaseModel

from app.config import load_config
from app.corpus import DATA_DIR
from app.llm.client import LLMClient, LLMResponseError
from app.schemas import Event, ExposurePath, Portfolio, PortfolioNode

ROOT = "기관"

# 국가코드 → 지역 그룹. 사건 regions의 EU는 유럽 전체(영국·스위스·노르웨이 포함)로 본다.
REGION_GROUPS = {
    "EU": {"AT", "BE", "CH", "CZ", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HU", "IE", "IT", "LU", "NL", "NO",
           "PL", "PT", "SE"},
    "EM": {"AE", "AR", "BR", "CL", "CN", "CO", "EG", "HK", "ID", "IN", "KR", "KW", "MX", "MY", "NG", "PE", "PH",
           "PK", "QA", "RU", "SA", "TH", "TR", "TW", "UA", "ZA"},
}


class ExposureUnavailable(RuntimeError):
    """해당 사건 시점의 보유내역 스냅샷이 없음 (예: gfc_2008)."""


def _cfg() -> dict:
    return load_config()["exposure"]


def region_tags(codes: list[str]) -> set[str]:
    tags = set(codes)
    for code in codes:
        tags |= {g for g, members in REGION_GROUPS.items() if code in members}
    return tags


def region_score(codes: list[str], event: Event) -> float:
    if region_tags(codes) & set(event.regions):
        return 1.0
    return _cfg()["global_region_score"] if "GLOBAL" in event.regions or "GLOBAL" in codes else 0.0


def relevance(regions: list[str], sectors: list[str], asset_classes: list[str], event: Event) -> tuple[float, list[str]]:
    """규칙 기반 연관도와 일치 근거 목록."""
    w = _cfg()["relevance_weights"]
    r = region_score(regions, event)
    s = 1.0 if set(sectors) & set(event.sectors) else 0.0
    a = 1.0 if set(asset_classes) & set(event.asset_classes) else 0.0
    reasons = []
    if r:
        reasons.append("지역 " + ",".join(sorted(region_tags(regions) & set(event.regions)) or ["GLOBAL"]))
    if s:
        reasons.append("업종 " + ",".join(sorted(set(sectors) & set(event.sectors))))
    if a:
        reasons.append("자산군 " + ",".join(sorted(set(asset_classes) & set(event.asset_classes))))
    return w["region"] * r + w["sector"] * s + w["asset_class"] * a, reasons


# ---------- 보유내역 ----------


def load_holdings(ticker: str, snapshot: str) -> pd.DataFrame:
    path = DATA_DIR / "holdings" / f"{ticker}_{snapshot}.parquet"
    if not path.exists():
        raise ExposureUnavailable(f"{ticker} {snapshot} 스냅샷 없음")
    df = pd.read_parquet(path)
    df = df[~df["asset_cat"].isin(_cfg()["excluded_asset_cats"]) & (df["pct_val"].fillna(0) > 0)]
    return df.assign(country=df["country"].fillna("XX"))


# ---------- 이름 매칭 ----------

_SUFFIX = {"inc", "corp", "corporation", "co", "company", "group", "holdings", "holding", "ltd", "plc", "na", "sa",
           "ag", "nv", "the", "of", "ny", "new", "york", "ca", "llc", "lp"}


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in _SUFFIX}


def rule_match(entity: str, issuers: list[str]) -> list[str]:
    """법인 접미사·소재지를 뗀 이름 토큰이 완전히 같을 때만 매칭 (예: 'Signature Bank/New York NY')."""
    et = _name_tokens(entity)
    return [i for i in issuers if et and _name_tokens(i) == et]


class EntityMatch(BaseModel):
    entity: str
    issuer: str


class EntityMatches(BaseModel):
    matches: list[EntityMatch]


MATCH_SYSTEM = """사건에 등장한 기관명과 펀드 보유 발행자명을 대조한다.
같은 법인이거나 그 지주회사·자회사인 경우에만 매칭한다. 확실하지 않으면 매칭하지 않는다.
- 이름 일부나 지역명이 겹친다는 이유로 매칭하지 않는다 (예: 'Bank of Korea'와 'Industrial Bank of Korea'는 다른 회사).
- 업종이 같다는 이유로 매칭하지 않는다.
- 중앙은행·정부부처·감독기관·국제기구는 그 나라 국채나 다른 기업과 매칭하지 않는다.
issuer는 반드시 후보 목록의 문자열을 그대로 사용한다. 매칭이 없으면 빈 목록을 반환한다."""


_PUBLIC = re.compile(
    r"central bank|federal reserve|reserve bank|bank of korea|ministry|department|treasury|government|province|"
    r"commission|authority|fdic|world health|white house|swift|monetary fund|위원회|정부", re.I)


def is_public_body(entity: str) -> bool:
    """중앙은행·정부·감독기관·국제기구는 보유 발행자와 매칭하지 않는다 (LLM 오탐 방지)."""
    return bool(_PUBLIC.search(entity))


def match_entities(event: Event, issuers: list[str], llm: LLMClient | None) -> dict[str, str]:
    """issuer → 매칭된 사건 entity. 규칙 매칭 실패한 민간 entity만 LLM 보조."""
    found: dict[str, str] = {}
    unmatched = []
    for ent in (e for e in event.entities if not is_public_body(e)):
        hits = rule_match(ent, issuers)
        found.update({h: ent for h in hits})
        if not hits:
            unmatched.append(ent)
    if unmatched and llm is not None and issuers:
        prompt = "[사건 기관명]\n" + "\n".join(unmatched) + "\n\n[보유 발행자 후보]\n" + "\n".join(issuers)
        try:
            res = llm.generate(prompt, purpose="exposure_entity_match", response_schema=EntityMatches, system=MATCH_SYSTEM)
            valid = set(issuers)
            found.update({m.issuer: m.entity for m in res.matches if m.issuer in valid and m.entity in unmatched})
        except LLMResponseError:
            pass
    return found


# ---------- 그래프·경로 ----------


@dataclass
class PathDetail:
    nodes: list[str]
    portfolio_node: str
    labels: list[str]  # 노드 설명 (why 생성용 경로 속성)
    weight: float
    relevance: float
    uncertainty: float
    reasons: list[str]
    regions: list[str] = field(default_factory=list)

    @property
    def risk_score(self) -> float:
        return self.weight * self.relevance * (1 - _cfg()["uncertainty_penalty"] * self.uncertainty)


@dataclass
class ExposureReport:
    event_id: str
    snapshot: str
    paths: list[ExposurePath]
    portfolio_nodes: list[str]  # paths와 같은 순서의 포트폴리오 노드 id
    uncertain_ratio: float
    needs_requery: bool
    entity_matches: dict[str, str] = field(default_factory=dict)
    entity_paths: list[ExposurePath] = field(default_factory=list)  # 사건 기관과 같은 발행자 보유 (순위와 별도 표시)
    core_paths: list[ExposurePath] = field(default_factory=list)  # 사건의 구체 지역(GLOBAL 제외)과 일치하는 경로 (상위 N 밖)
    graph: nx.DiGraph | None = None


_KIND = {"direct": "직접 보유", "manager": "위탁운용사", "counterparty": "거래상대방"}


def _kind_label(n: PortfolioNode) -> str:
    return f"{_KIND[n.kind]} {n.name} ({n.instrument})"


def _leaf(regions: list[str], sectors: list[str]) -> str:
    return f"{'/'.join(regions) or '-'} · {'/'.join(sectors) or '-'}"


def build_paths(event: Event, portfolio: Portfolio, snapshot: str, llm: LLMClient | None) -> tuple[list[PathDetail], dict[str, str], nx.DiGraph]:
    cfg = _cfg()
    g = nx.DiGraph()
    g.add_node(ROOT, kind="institution")
    holdings: dict[str, pd.DataFrame] = {}
    node_rel: dict[str, float] = {}
    for n in portfolio.nodes:
        node_rel[n.id], _ = relevance(n.regions, n.sectors, n.asset_classes, event)
        if n.proxy_fund:
            holdings[n.id] = load_holdings(n.proxy_fund.ticker, snapshot)

    # 이름 매칭 후보: 사건과 조금이라도 연관된 노드의 펀드 발행자 (비중 큰 순)
    cand = pd.concat([df for nid, df in holdings.items() if node_rel[nid] > 0] or [pd.DataFrame(columns=["issuer", "pct_val"])])
    issuers = (cand.dropna(subset=["issuer"]).sort_values("pct_val", ascending=False)["issuer"]
               .drop_duplicates().head(cfg["entity_candidates_max"]).tolist())
    matches = match_entities(event, issuers, llm) if event.entities else {}

    paths: list[PathDetail] = []
    for n in portfolio.nodes:
        g.add_node(n.id, kind=n.kind, name=n.name, weight=n.weight, uncertainty=n.uncertainty)
        g.add_edge(ROOT, n.id, weight=n.weight)
        if n.id not in holdings:
            rel, reasons = relevance(n.regions, n.sectors, n.asset_classes, event)
            leaf = _leaf(n.regions, n.sectors)
            g.add_edge(n.id, leaf, weight=n.weight)
            paths.append(PathDetail([ROOT, n.id, leaf], n.id, [_kind_label(n), leaf], n.weight, rel, n.uncertainty, reasons,
                                    list(n.regions)))
            continue
        paths += _fund_paths(g, n, holdings[n.id], matches, event)

    min_rel = cfg["min_relevance"]
    return [p for p in paths if p.relevance >= min_rel and p.weight > 0], matches, g


def _fund_paths(g: nx.DiGraph, n: PortfolioNode, df: pd.DataFrame, matches: dict[str, str], event: Event) -> list[PathDetail]:
    fund = n.proxy_fund.ticker
    g.add_node(fund, kind="fund", name=n.proxy_fund.name)
    g.add_edge(n.id, fund, weight=n.weight)
    out = []
    is_entity = df["issuer"].isin(matches)
    # 사건 entity와 매칭된 발행자는 발행자별 개별 경로 (relevance 1)
    for (issuer, country), grp in df[is_entity].groupby(["issuer", "country"]):
        w = n.weight * grp["pct_val"].sum() / 100
        leaf = _leaf([country], n.sectors)
        g.add_edge(fund, issuer, weight=w)
        g.add_edge(issuer, leaf, weight=w)
        out.append(PathDetail([ROOT, n.id, fund, issuer, leaf], n.id,
                              [_kind_label(n), f"프록시 펀드 {n.proxy_fund.name}", f"보유 발행자 {issuer}", leaf],
                              w, 1.0, n.uncertainty, [f"사건 기관 '{matches[issuer]}'과 동일 발행자"], [country]))
    # 나머지는 국가별 묶음 경로
    for country, grp in df[~is_entity].groupby("country"):
        w = min(n.weight * grp["pct_val"].sum() / 100, n.weight)
        rel, reasons = relevance([country], n.sectors, n.asset_classes, event)
        holding = f"{fund} {country} 보유 {len(grp)}종목"
        leaf = _leaf([country], n.sectors)
        g.add_edge(fund, holding, weight=w)
        g.add_edge(holding, leaf, weight=w)
        out.append(PathDetail([ROOT, n.id, fund, holding, leaf], n.id,
                              [_kind_label(n), f"프록시 펀드 {n.proxy_fund.name}", holding, leaf],
                              w, rel, n.uncertainty, reasons, [country]))
    return out


# ---------- why ----------


class WhyList(BaseModel):
    whys: list[str]


WHY_SYSTEM = """기관투자자의 보유 경로마다 이번 사건과 관련해 왜 확인해야 하는지 한국어 한 문장으로 쓴다.
- 주어진 경로 속성(노드 설명, 비중, 연관도, 불확실성, 일치 근거)만 사용하고 새로운 사실을 지어내지 않는다.
- 숫자를 나열하지 말고, 어떤 경로(직접/위탁운용사/거래상대방 → 펀드 → 보유)로 노출되는지와 무엇이 일치하는지를 설명한다.
- 불확실성이 0보다 크면 프록시 추정 또는 거래상대방 노출이라 실제와 다를 수 있음을 짧게 언급한다.
입력 순서대로 같은 개수의 문장을 반환한다."""


def _fallback_why(p: PathDetail) -> str:
    return f"{' → '.join(p.labels)}: 비중 {p.weight:.2%}, {', '.join(p.reasons) or '연관 근거 약함'} (불확실성 {p.uncertainty:.1f})"


def explain(paths: list[PathDetail], llm: LLMClient | None) -> list[str]:
    if not paths or llm is None:
        return [_fallback_why(p) for p in paths]
    items = [{"경로": p.labels, "비중": f"{p.weight:.2%}", "연관도": round(p.relevance, 3),
              "불확실성": p.uncertainty, "일치 근거": p.reasons} for p in paths]
    try:
        res = llm.generate(json.dumps(items, ensure_ascii=False, indent=1), purpose="exposure_why",
                           response_schema=WhyList, system=WHY_SYSTEM)
    except LLMResponseError:
        return [_fallback_why(p) for p in paths]
    if len(res.whys) != len(paths):
        return [_fallback_why(p) for p in paths]
    return [w.strip() or _fallback_why(p) for w, p in zip(res.whys, paths)]


# ---------- 전체 ----------


def snapshot_for(event: Event, live: bool = False) -> str:
    return "live" if live else event.id


def uncertain_ratio(paths: list[PathDetail]) -> float:
    if not paths:
        return 0.0
    th = _cfg()["uncertain_path_threshold"]
    return sum(p.uncertainty >= th for p in paths) / len(paths)


def core_paths(paths: list[PathDetail], top: list[PathDetail], event: Event, limit: int) -> list[PathDetail]:
    """사전 등록 v2: 상위 N 밖에서, 사건의 구체 지역(GLOBAL 제외)과 지역이 일치하는 경로를 risk 순으로."""
    specific = set(event.regions) - {"GLOBAL"}
    in_top = {id(p) for p in top}
    hits = [p for p in paths if id(p) not in in_top and region_tags(p.regions) & specific]
    return sorted(hits, key=lambda p: p.risk_score, reverse=True)[:limit]


def _to_path(p: PathDetail, why: str) -> ExposurePath:
    return ExposurePath(nodes=p.nodes, weight=round(p.weight, 6), relevance=round(p.relevance, 4),
                        uncertainty=p.uncertainty, risk_score=round(p.risk_score, 6), why=why)


def compute_exposure(event: Event, portfolio: Portfolio, llm: LLMClient | None, live: bool = False,
                     top_n: int | None = None) -> ExposureReport:
    cfg = _cfg()
    snapshot = snapshot_for(event, live)
    paths, matches, g = build_paths(event, portfolio, snapshot, llm)
    top = sorted(paths, key=lambda p: p.risk_score, reverse=True)[: top_n or cfg["top_n"]]
    entity = sorted((p for p in paths if p.relevance == 1.0 and len(p.nodes) == 5 and p.reasons
                     and p.reasons[0].startswith("사건 기관")), key=lambda p: p.risk_score, reverse=True)
    whys = explain(top, llm)
    ratio = uncertain_ratio(top)
    core = core_paths(paths, top, event, cfg.get("core_paths_max", 5))
    return ExposureReport(
        event_id=event.id,
        snapshot=snapshot,
        paths=[_to_path(p, w) for p, w in zip(top, whys)],
        portfolio_nodes=[p.portfolio_node for p in top],
        uncertain_ratio=round(ratio, 3),
        needs_requery=ratio > cfg["requery_uncertain_ratio"],
        entity_matches=matches,
        entity_paths=[_to_path(p, _fallback_why(p)) for p in entity],
        core_paths=[_to_path(p, _fallback_why(p)) for p in core],
        graph=g,
    )
