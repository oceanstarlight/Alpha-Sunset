from datetime import datetime, timezone

from app import geo
from app.corpus import load_events, load_portfolio
from app.data.gdelt import Article


def _event(eid):
    return {e.id: e for e in load_events()}[eid]


def test_centroids_cover_portfolio_countries_and_namibia():
    assert geo.locate("KR")[2] == "South Korea"
    assert geo.locate("NA")[2] == "Namibia"  # 'NA'가 결측값으로 읽히면 안 됨
    assert geo.locate("EU") is not None and geo.locate("GLOBAL") is None


def test_exposure_and_impact_by_country():
    p = load_portfolio()
    exp = geo.country_exposure(p, "svb_2023")
    assert max(exp, key=exp.get) in {"US", "KR"}
    total_nodes = sum(n.weight for n in p.nodes)
    assert abs(sum(exp.values()) - total_nodes) < 0.05  # 국가로 나눠도 노드 비중 합과 거의 같다
    imp = geo.country_impact(_event("svb_2023"), p, "svb_2023")
    assert max(imp, key=imp.get) == "US"  # 미국 은행 사건 → 미국 영향 최대


def test_map_rows_layers_and_unmapped():
    e = _event("ru_ua_2022")
    df, unmapped = geo.map_rows(event=e, exposure_by_country={"US": 0.4, "GLOBAL": 0.01},
                                coverage_by_name={"South Korea": 3, "Atlantis": 1})
    assert set(df["layer"]) == {geo.LAYERS[k]["label"] for k in ("event", "exposure", "coverage")}
    assert set(df[df["layer"] == geo.LAYERS["event"]["label"]]["code"]) == {"RU", "UA", "EU"}
    assert unmapped == {"exposure": ["GLOBAL"], "coverage": ["Atlantis"], "event": ["GLOBAL"]}
    assert df["radius"].max() > 0


def test_gdelt_coverage_counts_source_countries():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    class Fake:
        def articles(self, query, timespan="1d"):
            if "tariff" in query:
                raise RuntimeError("429")
            return [Article("t", "https://a/1", "a.com", now, "United States"),
                    Article("t2", "https://b/1", "b.com", now, "South Korea")]

    cov = geo.gdelt_coverage(Fake())
    assert cov["status"] == "partial" and len(cov["errors"]) == 1
    assert cov["countries"] == {"United States": 7, "South Korea": 7}
