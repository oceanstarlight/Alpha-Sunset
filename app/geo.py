"""세계 금융 지도용 국가별 집계 (사건 지역 · 보유 비중 · 영향도 · GDELT 보도 국가)."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Any

import pandas as pd

from app.agents import exposure
from app.config import ROOT_DIR, load_config
from app.schemas import Event, Portfolio

CENTROIDS_PATH = ROOT_DIR / "data" / "geo" / "country_centroids.csv"

# 국가 하나로 찍을 수 없는 지역 묶음. EU만 대표 좌표(브뤼셀)에 표시하고, EM·GLOBAL은 표로만 보여준다.
GROUP_ANCHORS = {"EU": (50.85, 4.35, "유럽(EU 묶음)")}

# GDELT sourcecountry 표기 → ISO 코드 (중심 좌표 표의 이름과 다른 것만)
GDELT_ALIASES = {
    "Czech Republic": "CZ", "Ivory Coast": "CI", "Cote d'Ivoire": "CI", "Burma": "MM", "Macedonia": "MK",
    "Congo": "CG", "Democratic Republic of the Congo": "CD", "Korea, South": "KR", "Korea, North": "KP",
    "Bahamas, The": "BS", "Gambia, The": "GM", "Vatican City": "VA", "Palestine": "PS", "Timor-Leste": "TL",
}

LAYERS = {
    "event": {"label": "사건 지역", "color": [220, 38, 38, 150]},
    "exposure": {"label": "보유 비중", "color": [37, 99, 235, 110]},
    "impact": {"label": "영향도 (비중×연관도)", "color": [249, 115, 22, 170]},
    "coverage": {"label": "GDELT 보도 국가", "color": [147, 51, 234, 120]},
}


@lru_cache
def centroids() -> pd.DataFrame:
    return pd.read_csv(CENTROIDS_PATH, keep_default_na=False).set_index("code")  # NA(나미비아)가 결측으로 읽히지 않게


def locate(code: str) -> tuple[float, float, str] | None:
    if code in GROUP_ANCHORS:
        return GROUP_ANCHORS[code]
    df = centroids()
    if code not in df.index:
        return None
    row = df.loc[code]
    return float(row["lat"]), float(row["lon"]), str(row["name"])


def code_for_name(name: str) -> str | None:
    if name in GDELT_ALIASES:
        return GDELT_ALIASES[name]
    hit = centroids().index[centroids()["name"] == name]
    return str(hit[0]) if len(hit) else None


# ---------- 국가별 집계 ----------


def country_exposure(portfolio: Portfolio, snapshot: str) -> dict[str, float]:
    """국가(또는 지역 묶음)별 보유 비중. 펀드 노드는 보유 국가 비중, 그 외는 노드 지역에 균등 배분."""
    out: dict[str, float] = defaultdict(float)
    for n in portfolio.nodes:
        if n.proxy_fund:
            df = exposure.load_holdings(n.proxy_fund.ticker, snapshot)
            by_country = df.groupby("country")["pct_val"].sum()
            total = max(float(by_country.sum()), 100.0)  # 파생·차입으로 합이 100%를 넘으면 노드 비중 안에서 정규화
            for country, pct in by_country.items():
                out[country] += n.weight * float(pct) / total
        else:
            for r in n.regions:
                out[r] += n.weight / len(n.regions)
    return dict(out)


def country_impact(event: Event, portfolio: Portfolio, snapshot: str) -> dict[str, float]:
    """국가별 영향도 = 노출 경로 risk_score 합 (exposure.build_paths, LLM 없이 규칙 매칭만)."""
    paths, _, _ = exposure.build_paths(event, portfolio, snapshot, llm=None)
    out: dict[str, float] = defaultdict(float)
    for p in paths:
        for r in p.regions or ["GLOBAL"]:
            out[r] += float(p.risk_score) / max(len(p.regions), 1)
    return dict(out)


def gdelt_coverage(client: Any, timespan: str = "1d") -> dict:
    """주제 쿼리별 최근 기사의 보도 매체 국가 분포 (사건 발생 위치가 아니다. GDELT GEO API는 404라 사용 불가)."""
    queries = load_config()["sentinel"]["news"]["queries"]
    countries: dict[str, int] = defaultdict(int)
    by_query, errors = {}, []
    for event_type, query in queries.items():
        try:
            arts = client.articles(query, timespan=timespan)
        except Exception as e:
            errors.append(f"{event_type}: {e}")
            continue
        for a in arts:
            if a.source_country:
                countries[a.source_country] += 1
        by_query[event_type] = {"n_articles": len(arts), "top_titles": [a.title for a in arts[:3]]}
    return {"timespan": timespan, "countries": dict(countries), "by_query": by_query, "errors": errors,
            "status": "unavailable" if len(errors) >= len(queries) else ("partial" if errors else "ok")}


# ---------- 지도 행 ----------


def _rows(layer: str, values: dict[str, float], max_radius_m: float, fmt) -> tuple[list[dict], list[str]]:
    rows, unmapped = [], []
    top = max(values.values(), default=0)
    for code, v in sorted(values.items(), key=lambda kv: -kv[1]):
        loc = locate(code)
        if loc is None or v <= 0 or top <= 0:
            if v > 0:
                unmapped.append(code)
            continue
        lat, lon, name = loc
        rows.append({"layer": LAYERS[layer]["label"], "code": code, "name": name, "lat": lat, "lon": lon,
                     "value": v, "radius": max_radius_m * (v / top) ** 0.5, "color": LAYERS[layer]["color"],
                     "tooltip": f"{LAYERS[layer]['label']} · {name}: {fmt(v)}"})
    return rows, unmapped


def map_rows(event: Event | None = None, exposure_by_country: dict[str, float] | None = None,
             impact_by_country: dict[str, float] | None = None,
             coverage_by_name: dict[str, int] | None = None) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """지도 원 데이터. 반환: (행, 레이어별 좌표 없는 지역 코드)."""
    rows: list[dict] = []
    unmapped: dict[str, list[str]] = {}
    if exposure_by_country:
        r, unmapped["exposure"] = _rows("exposure", exposure_by_country, 1_200_000, lambda v: f"{v:.2%}")
        rows += r
    if coverage_by_name:
        by_code: dict[str, float] = defaultdict(float)
        for name, n in coverage_by_name.items():
            code = code_for_name(name)
            by_code[code or name] += n
        r, unmapped["coverage"] = _rows("coverage", dict(by_code), 1_000_000, lambda v: f"기사 {v:.0f}건")
        rows += r
    if impact_by_country:
        r, unmapped["impact"] = _rows("impact", impact_by_country, 900_000, lambda v: f"{v:.4f}")
        rows += r
    if event:
        sev = {code: float(event.severity) for code in event.regions}
        r, unmapped["event"] = _rows("event", sev, 300_000 * event.severity, lambda v: f"심각도 {v:.0f}/5")
        for row in r:
            row["tooltip"] = f"사건 지역 · {row['name']}: {event.title} (심각도 {event.severity}/5)"
        rows += r
    return pd.DataFrame(rows), {k: v for k, v in unmapped.items() if v}
