from datetime import date

import numpy as np
import pandas as pd

from app import backtest_kr as bk


def _panel(shock_day="2022-09-29"):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2019-01-01", "2023-06-30")
    def walk(scale):
        return pd.Series(100 + rng.normal(0, scale, len(idx)).cumsum(), index=idx)
    kospi, usd, ktb, corp, cd = walk(1), walk(1), walk(0.02), walk(0.02), walk(0.01)
    d = pd.Timestamp(shock_day)
    for day in (d, d + pd.offsets.BDay(1)):  # 이틀 연속 신용 스프레드 급등 (5영업일 중 2일 조건)
        corp.loc[day:] += 0.6
        ktb.loc[day:] -= 0.3
    flow = pd.Series(rng.normal(0, 100, len(idx)), index=idx)
    from app.agents import local
    return local.kr_panel({"KOSPI": kospi, "USDKRW": usd, "KTB3Y": ktb, "CORP_AA3Y": corp, "CD91": cd,
                           "FOREIGN_NET_KOSPI": flow})


def test_event_row_finds_credit_shock_before_event_and_records_cause():
    panel = _panel()
    row = bk.event_row(panel, date(2022, 10, 4), card_days=14)
    assert row["first_kr_money_alert"] is not None and row["kr_warning_lead_days"] >= 0
    assert {"CREDIT_KR", "KTB3Y"} & set(row["kr_money_alert_cause"])


def test_calm_rates_are_rates_and_exclude_events():
    panel = _panel()
    r = bk.calm_rates(panel, [date(2022, 9, 29)], "2020-06-01", "2023-06-30", 180)
    assert 0 <= r["kr_calm_money_alert_rate"] < 0.2 and 0 <= r["kr_base_rate"] <= 1 and r["n_calm_days"] > 300


def test_flow_z_excludes_same_day():
    idx = pd.bdate_range("2022-01-03", periods=80)
    s = pd.Series(1.0, index=idx) + np.arange(80) % 3
    s.iloc[-1] = 1000
    z = bk.kr_flow_z({"FOREIGN_NET_KOSPI": s}, idx)
    assert z["FOREIGN_NET_KOSPI"].iloc[-1] > 3  # 당일 값이 기준선에 섞이지 않아야 급등이 잡힌다
