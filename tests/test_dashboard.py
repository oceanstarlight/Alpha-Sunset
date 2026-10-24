"""탭 상단 요약·그래프 (app/dashboard.py)."""

import json

import pandas as pd

from app import dashboard, services
from app.config import ROOT_DIR

KR = json.loads((ROOT_DIR / "data" / "live" / "kr_latest.json").read_text(encoding="utf-8"))


def test_watch_local_none_explains_why():
    s = dashboard.watch_local(KR | {"level": "NONE"})
    text = "\n".join(s.bullets)
    assert s.tone == "green" and "NONE" in s.headline
    assert "한국 시장(A)" in text and "외국인 자금(C)" in text and "할 일" in text


def test_signal_line_near_and_over_threshold():
    assert "임계 초과" in dashboard._signal_line("A", {"x": 3.0}, ["x"], 2.5)
    assert "임계 근접" in dashboard._signal_line("A", {"x": -2.0}, [], 2.5)
    assert "정상" in dashboard._signal_line("A", {"x": 0.5}, [], 2.5)


def test_news_line_baseline_accumulating():
    news = {"status": "unavailable", "clusters": [], "observations": {"a": {"baseline_points": 4}, "b": {"baseline_points": 6}}}
    assert "기준선 축적 중 4/20" in dashboard._news_line("B", news, 20)


def test_briefing_and_approval_summary():
    b = services.load_saved_briefing("svb_2023")
    s = dashboard.briefing(b)
    assert b.match.doc_fits[0].doc_id in s.bullets[0] and s.tone in ("red", "orange", "green")
    assert dashboard.briefing(b, scenario=True).tone == "blue"
    recs = [{"action": "approval", "actor": "kim", "ts": "2026-10-24T10:00:00", "data": {"run_id": b.run_id, "decision": "approved"}},
            {"action": "feedback", "actor": "kim", "ts": "x", "data": {"run_id": b.run_id, "label": "useful"}},
            {"action": "feedback", "actor": "kim", "ts": "x", "data": {"run_id": "other", "label": "useful"}}]
    a = dashboard.approval(b, recs)
    assert a.tone == "green" and "승인 완료" in a.headline and "1건" in a.bullets[1]
    assert dashboard.approval(b, []).headline == "승인 대기"


def test_backtest_summary_uses_adopted_v6():
    s = dashboard.backtest(services.get_backtest_results(), local=True)
    text = "\n".join(s.bullets)
    assert "17/23" in text and "κ" in text and "우연과 구분 안 됨" in text


def test_charts_build_and_handle_empty():
    b = services.load_saved_briefing("svb_2023")
    res = services.get_backtest_results()
    charts = [dashboard.z_chart({"a": 1.0, "b": -3.0}, 2.5, "t"), dashboard.news_chart(KR["kr_news"]["observations"], 3, "t"),
              dashboard.fit_chart(b.match.doc_fits), dashboard.exposure_chart(b.exposure_top), dashboard.actions_chart(b.actions_to_check),
              dashboard.capture_chart(res["v6"]), dashboard.lead_chart(res["v6"]), dashboard.confusion_chart(res["clause_eval"]["overall"]["confusion"]),
              dashboard.weight_chart(pd.DataFrame({"sector": ["a", "b", None], "weight": [0.5, 0.3, 0.2]}), "sector", "t"),
              dashboard.country_chart({"US": 0.5, "KR": 0.2}, "t")]
    for c in charts:
        assert c is not None and c.to_dict()
    assert dashboard.z_chart({}, 2.5, "t") is None and dashboard.fit_chart([]) is None and dashboard.priority_chart([]) is None
