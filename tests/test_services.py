from pathlib import Path

from app import services
from app.db import connect
from app.schemas import Feedback


def test_saved_briefings_load_for_all_events():
    for eid in ["gfc_2008", "covid_2020", "ru_ua_2022", "legoland_2022", "svb_2023", "tariff_2025"]:
        b = services.load_saved_briefing(eid)
        assert b is not None and b.event.id == eid


def test_feedback_writes_feedback_and_shadow_log():
    b = services.load_saved_briefing("svb_2023")
    services.submit_feedback(Feedback(run_id=b.run_id, doc_id="PB-BANK", label="useful", user_id="u1"), b)
    conn = connect("sandbox")
    assert conn.execute("SELECT label FROM feedback").fetchall()[0][0] == "useful"
    row = conn.execute("SELECT event_id, doc_id, rank, feedback, mode FROM shadow_log").fetchone()
    conn.close()
    assert tuple(row) == ("svb_2023", "PB-BANK", 1, "useful", "backtest")
    conn = connect("live")
    assert conn.execute("SELECT COUNT(*) FROM shadow_log").fetchone()[0] == 0  # 라이브에 섞이지 않음
    conn.close()


def test_priority_aggregates_shadow_log():
    b = services.load_saved_briefing("svb_2023")
    services.submit_feedback(Feedback(run_id=b.run_id, doc_id="PB-BANK", label="not_fit", user_id="u1"), b)
    pr = services.get_priority()
    assert pr["docs"][0]["doc_id"] == "PB-BANK" and pr["docs"][0]["not_fit"] == 1


def test_approval_recorded_in_trace():
    b = services.load_saved_briefing("svb_2023")
    services.record_approval(b, "approved", "u1", "확인")
    trace = services.get_trace(b.trace_id)
    assert trace[-1]["tool"] == "human_approval" and trace[-1]["output_summary"] == "approved"


def test_backtest_results_available():
    res = services.get_backtest_results()
    assert res["sentinel"]["events"] and res["match"] and "svb_2023" in res["exposure"]


def test_live_returns_none_without_news(monkeypatch):
    signals = {"news": {"clusters": []}}
    assert services.run_live(signals) is None


def test_ui_renders_without_exceptions():
    from streamlit.testing.v1 import AppTest

    app = Path(__file__).resolve().parent.parent / "ui" / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=120).run()
    assert not at.exception
    assert len(at.tabs) == 5
    at.sidebar.selectbox[0].set_value("svb_2023").run()
    assert not at.exception
    assert any("SVB" in m.value or "실리콘밸리" in m.value for m in at.markdown)
