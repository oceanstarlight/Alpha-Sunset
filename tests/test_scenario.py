"""시나리오 브리핑: 감시 등급과 무관하게 가정 사건으로 브리핑."""

from app import audit, services
from app.schemas import Channel, EventType


def test_scenario_event_defaults_and_overrides():
    e = services.scenario_event("liquidity_crisis", "PF 부실로 단기자금시장 경색\n증권사 CP 금리 급등", regions=["KR"])
    assert e.id.startswith("scenario_") and e.type == EventType.liquidity_crisis
    assert e.title == "PF 부실로 단기자금시장 경색" and Channel.liquidity in e.channels
    assert e.sources == ["사용자 입력 (가정 시나리오)"]
    e2 = services.scenario_event("fx_shock", "", title="원화 급락", channels=["fx", "rates"], severity=5, entities=["A은행"])
    assert e2.title == "원화 급락" and e2.channels == [Channel.fx, Channel.rates] and e2.entities == ["A은행"]


def test_run_scenario_rule_provider_end_to_end(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rule")  # 키 없이 끝까지 (규칙 판정)
    e = services.scenario_event("banking_stress", "지역은행 뱅크런, 예금 인출 급증", regions=["US"])
    b = services.run_scenario(e)
    assert services.is_scenario(b) and b.match.doc_fits
    assert b.match.doc_fits[0].doc_id == "PB-BANK"
    assert "가정 시나리오" in b.exposure_note
    rec = audit.read("app")[-1]
    assert rec["action"] == "briefing" and rec["data"]["mode"] == "scenario" and rec["data"]["provider"] == "rule"


def test_ondemand_topics_and_event_without_detected_event():
    import json

    from app.config import ROOT_DIR

    kr = json.loads((ROOT_DIR / "data" / "live" / "kr_latest.json").read_text(encoding="utf-8"))
    topics, default, why = services.ondemand_topics(kr)
    assert default in topics and "기사 수가 가장 많은" in why  # 기준선 축적 중 → 기사 수 최다 주제
    e = services.ondemand_event(kr, default, local=True)
    assert e.id.startswith("ondemand_") and e.regions == ["KR"] and "직접 실행" in e.summary
    glob = {"level": "WATCH", "market": {"zscores": {"VIX": 2.1}}, "news": {"clusters": [], "observations": {
        "banking_stress": {"n_articles": 30, "n_sources": 20, "z": 1.5, "top_titles": ["A bank"]},
        "geopolitical": {"n_articles": 90, "n_sources": 50, "z": -0.3, "top_titles": []}}}}
    topics, default, why = services.ondemand_topics(glob)
    assert default == "banking_stress" and "z +1.50" in why
    e2 = services.ondemand_event(glob, default, local=False)
    assert e2.severity == 3 and "A bank" in e2.summary and e2.regions == ["GLOBAL"]


def test_run_ondemand_rule_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rule")
    glob = {"level": "NONE", "market": {"zscores": {}}, "news": {"clusters": [], "observations": {
        "liquidity_crisis": {"n_articles": 10, "n_sources": 8, "z": None}}}}
    b = services.run_ondemand(services.ondemand_event(glob, "liquidity_crisis", local=False))
    assert services.briefing_kind(b) == "ondemand" and b.match.doc_fits
    assert "직접 실행" in b.exposure_note
    assert audit.read("app")[-1]["data"]["mode"] == "ondemand"
