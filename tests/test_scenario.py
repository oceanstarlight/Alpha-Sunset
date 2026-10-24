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
