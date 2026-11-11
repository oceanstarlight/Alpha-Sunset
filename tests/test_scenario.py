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
    from tests.conftest import kr_accumulating

    kr = kr_accumulating()
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


def _hot_panel(days: int = 400, as_of=None):
    """마지막 날 VIX·HY 스프레드가 급등한 합성 패널 (시장 신호 A 활성)."""
    import numpy as np
    import pandas as pd

    from app.agents import sentinel

    end = pd.Timestamp(as_of or services._today_kst())
    idx = pd.bdate_range(end=end, periods=days)
    rng = np.random.default_rng(0)
    panel = {}
    for sid in sentinel.panel_series_ids():
        s = pd.Series(20 + rng.normal(0, 0.2, len(idx)).cumsum() * 0.05, index=idx)
        s.iloc[-1] = s.iloc[-2] + 25  # 하루 급등
        panel[sid] = s
    return panel


def test_unconfirmed_event_is_not_graded_alert(monkeypatch):
    """가정 시나리오·확인 안 된 직접 실행은 시장 신호가 켜져도 ALERT가 아니다 (사건 확정 B로 치지 않음)."""
    monkeypatch.setenv("LLM_PROVIDER", "rule")
    panel = _hot_panel()
    monkeypatch.setattr(services, "live_panel", lambda: panel)
    e = services.scenario_event("banking_stress", "지역은행 뱅크런", regions=["US"])
    b = services.run_scenario(e)
    assert b.alert_level.value == "WATCH"
    glob = {"level": "NONE", "market": {"zscores": {}}, "news": {"clusters": [], "observations": {
        "banking_stress": {"n_articles": 10, "n_sources": 8, "z": None}}}}
    od = services.ondemand_event(glob, "banking_stress", local=False)
    assert services.run_ondemand(od, confirmed=services.topic_confirmed(glob, "banking_stress")).alert_level.value == "WATCH"
    # 감시가 기사량 급증으로 확인한 주제를 직접 실행하면 사건 확정 → ALERT
    glob["news"]["clusters"] = [{"event_type": "banking_stress", "z": 4.0, "n_sources": 30}]
    assert services.topic_confirmed(glob, "banking_stress")
    assert services.run_ondemand(od, confirmed=True).alert_level.value == "ALERT"


def test_live_briefing_market_signal_uses_fresh_panel_last_observation(monkeypatch):
    """커밋된 FRED 캐시(오래됨)가 아니라 최신 패널의 마지막 관측일로 시장 신호를 계산한다 (주말·공표 지연 포함)."""
    from datetime import timedelta

    from app.agents import orchestrator

    monkeypatch.setenv("LLM_PROVIDER", "rule")
    today = services._today_kst()
    panel = _hot_panel(as_of=today - timedelta(days=3))  # 마지막 관측 3일 전 (stale_days 5 이내)
    e = services.scenario_event("banking_stress", "지역은행 뱅크런", regions=["US"])
    ctx_seen = {}
    real = orchestrator.orchestrate

    def spy(ctx, task):
        ctx_seen["ctx"] = ctx
        return real(ctx, task)

    monkeypatch.setattr(orchestrator, "orchestrate", spy)
    monkeypatch.setattr(services, "live_panel", lambda: panel)
    services.run_scenario(e)
    ctx = ctx_seen["ctx"]
    assert ctx.market.zscores and ctx.market.active  # 오래된 캐시였다면 zscores가 비어 있음
    assert ctx.market.as_of == today - timedelta(days=3)
    # 마지막 관측이 stale_days보다 오래되면 신호로 쓰지 않는다
    monkeypatch.setattr(services, "live_panel", lambda: _hot_panel(as_of=today - timedelta(days=30)))
    services.run_scenario(e)
    assert not ctx_seen["ctx"].market.zscores
