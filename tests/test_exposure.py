from datetime import date

import pytest

from app.agents import exposure as ex
from app.agents.exposure import (
    EntityMatches,
    ExposureUnavailable,
    PathDetail,
    WhyList,
    compute_exposure,
    explain,
    is_public_body,
    match_entities,
    region_tags,
    relevance,
    rule_match,
    uncertain_ratio,
)
from app.corpus import load_events, load_portfolio
from app.schemas import Channel, Duration, Event, EventType

EVENT = Event(
    id="svb_2023", title="SVB", date=date(2023, 3, 10), summary="", type=EventType.banking_stress,
    channels=[Channel.liquidity], regions=["US"], sectors=["regional_banks"], asset_classes=["equity"],
    entities=["Silicon Valley Bank", "Signature Bank", "FDIC"], duration=Duration.weeks, severity=4,
)


class FakeLLM:
    def __init__(self, matches=None, whys=None):
        self.matches, self.whys, self.prompts = matches or [], whys, []

    def generate(self, prompt, purpose, response_schema=None, system=None):
        self.prompts.append((purpose, prompt))
        if response_schema is EntityMatches:
            return EntityMatches(matches=self.matches)
        n = prompt.count('"경로"')
        return WhyList(whys=self.whys if self.whys is not None else [f"이유 {i}" for i in range(n)])


def test_region_tags_and_score():
    assert {"KR", "EM"} <= region_tags(["KR"])
    assert "EU" in region_tags(["GB"])
    rel, reasons = relevance(["US"], ["regional_banks"], ["equity"], EVENT)
    assert rel == pytest.approx(1.0) and len(reasons) == 3
    assert relevance(["KR"], ["energy"], ["govt_bond"], EVENT)[0] == 0.0


def test_rule_match_is_strict():
    issuers = ["Signature Bank/New York NY", "Industrial Bank of Korea", "SVB Financial Group"]
    assert rule_match("Signature Bank", issuers) == ["Signature Bank/New York NY"]
    assert rule_match("Bank of Korea", issuers) == []
    assert rule_match("Silicon Valley Bank", issuers) == []


def test_public_bodies_never_matched():
    assert is_public_body("Central Bank of the Russian Federation")
    assert is_public_body("Gangwon Province")
    assert not is_public_body("Silicon Valley Bank")


def test_llm_assist_only_for_unmatched_private_entities_and_candidates():
    from app.agents.exposure import EntityMatch

    llm = FakeLLM(matches=[EntityMatch(entity="Silicon Valley Bank", issuer="SVB Financial Group"),
                           EntityMatch(entity="Silicon Valley Bank", issuer="지어낸 발행자")])
    found = match_entities(EVENT, ["SVB Financial Group", "Signature Bank/New York NY"], llm)
    assert found == {"Signature Bank/New York NY": "Signature Bank", "SVB Financial Group": "Silicon Valley Bank"}
    prompt = llm.prompts[0][1]
    assert "Silicon Valley Bank" in prompt and "FDIC" not in prompt and "Signature Bank\n" not in prompt.split("[보유")[0]


def _path(weight, rel, unc, nodes=("기관", "D-X", "leaf")):
    return PathDetail(list(nodes), nodes[1], ["설명"] * (len(nodes) - 1), weight, rel, unc, ["지역 US"])


def test_risk_score_formula():
    assert _path(0.1, 0.5, 0.3).risk_score == pytest.approx(0.1 * 0.5 * (1 - 0.5 * 0.3))


def test_uncertain_ratio_uses_threshold():
    assert uncertain_ratio([_path(0.1, 1, 0.5), _path(0.1, 1, 0.3)]) == 0.5
    assert uncertain_ratio([]) == 0.0


def test_why_falls_back_on_count_mismatch():
    paths = [_path(0.1, 1, 0), _path(0.2, 1, 0)]
    assert explain(paths, FakeLLM(whys=["하나만"]))[1].startswith("설명")
    assert explain(paths, FakeLLM()) == ["이유 0", "이유 1"]


def test_gfc_has_no_snapshot():
    gfc = next(e for e in load_events() if e.id == "gfc_2008")
    with pytest.raises(ExposureUnavailable):
        compute_exposure(gfc, load_portfolio(), None)


def test_svb_exposure_on_committed_holdings():
    from app.agents.exposure import EntityMatch

    svb = next(e for e in load_events() if e.id == "svb_2023")
    llm = FakeLLM(matches=[EntityMatch(entity="Silicon Valley Bank", issuer="SVB Financial Group")])
    rep = compute_exposure(svb, load_portfolio(), llm)
    assert len(rep.paths) == 10
    assert all(rep.paths[i].risk_score >= rep.paths[i + 1].risk_score for i in range(9))
    assert all(p.why for p in rep.paths)
    assert "M-HANBIT" in rep.portfolio_nodes
    hit = {p.nodes[3] for p in rep.entity_paths}
    assert {"SVB Financial Group", "Signature Bank/New York NY"} <= hit
    # 같은 발행자의 여러 증권은 한 경로로 합쳐진다
    keys = [(p.nodes[1], p.nodes[3]) for p in rep.entity_paths]
    assert len(keys) == len(set(keys))
    assert rep.graph.has_edge("M-HANBIT", "KRE")


def test_excluded_asset_categories_removed(monkeypatch):
    df = ex.load_holdings("KRE", "svb_2023")
    assert "STIV" not in set(df["asset_cat"])
    assert (df["pct_val"] > 0).all()
