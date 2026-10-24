from datetime import date

import numpy as np
import pandas as pd
import pytest

from app import backtest_v6 as v6


def test_v6_event_list_follows_registered_rule():
    events = v6.load_v6_events()
    assert len(events) == 23
    dates = sorted(e["date"] for e in events)
    assert all((b - a).days > 30 for a, b in zip(dates, dates[1:]))  # 30일 안 중복 없음
    assert dates[0] == date(1997, 7, 2) and dates[-1] == date(2025, 4, 2)


def test_binom_tail():
    assert v6.binom_tail(0, 10, 0.3) == pytest.approx(1.0)
    assert v6.binom_tail(10, 10, 0.5) == pytest.approx(0.5 ** 10)


def test_evaluate_counts_caught_lead_and_calm_rate():
    days = pd.bdate_range("2000-01-03", "2003-12-31")
    alert = pd.Series(False, index=days)
    alert.loc["2001-08-20":"2001-08-24"] = True  # 9·11 22일 전
    alert.loc["2002-06-03"] = True  # 평상일 알림 1일
    events = [{"id": "e1", "date": date(2001, 9, 11)}, {"id": "e2", "date": date(2003, 6, 2)}]
    m = v6.evaluate(alert, events, "2000-01-03", "2003-12-31")
    assert m["caught"] == 1 and m["prior_warning"] == 1 and m["events"][0]["lead_days"] == 22
    assert 0 < m["calm_alert_rate"] < 0.01 and 0 < m["base_rate_caught"] < 0.2


def test_alerts_persistence_rule():
    days = pd.bdate_range("2020-01-01", periods=10)
    mz = pd.DataFrame({"A": [0, 3, 3, 0, 0, 0, 0, 0, 0, 0], "B": [0, 3, 3, 3, 0, 0, 0, 0, 0, 0]}, index=days, dtype=float)
    fz = pd.DataFrame(index=days)
    a2 = v6.alerts(mz, fz, v6.Params(2.0, 2, 2, 3.5))
    a3 = v6.alerts(mz, fz, v6.Params(2.0, 2, 3, 3.5))
    assert a2.any() and not a3.any()  # 이틀 연속 활성: 5중 2는 알림, 5중 3은 아님
