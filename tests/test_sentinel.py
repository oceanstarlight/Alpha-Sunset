from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.agents.sentinel import (
    AsOfPanel,
    FutureDataError,
    MarketSignal,
    NewsCluster,
    NewsSignal,
    SentinelResult,
    card_news_signal,
    cluster_titles,
    grade,
    live_news_signal,
    market_signal,
    merge_alerts,
)
from app.data.gdelt import Article
from app.schemas import AlertLevel, Channel, Duration, Event, EventType

END = date(2024, 6, 28)


def calm_series(seed: int, n: int = 400, base: float = 100.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=END, periods=n)
    return pd.Series(base * np.exp(np.cumsum(rng.normal(0, 0.001, n))), index=idx)


def make_panel(shock: dict[str, float] | None = None) -> dict[str, pd.Series]:
    """모든 시리즈가 평온하고, shock에 지정된 시리즈만 마지막 날 배율로 튄다."""
    ids = ["VIXCLS", "T10Y2Y", "DGS10", "DEXKOUS", "DCOILWTICO", "DTWEXBGS", "BAA10Y"]
    panel = {sid: calm_series(i) for i, sid in enumerate(ids)}
    for sid, mult in (shock or {}).items():
        s = panel[sid].copy()
        s.iloc[-1] = s.iloc[-2] * mult
        panel[sid] = s
    return panel


def make_event(eid: str, d: date) -> Event:
    return Event(
        id=eid, title=eid, date=d, summary="", type=EventType.banking_stress,
        channels=[Channel.liquidity], duration=Duration.weeks, severity=3,
    )


# ---------- 시그널 A ----------


def test_calm_market_is_inactive():
    sig = market_signal(AsOfPanel(make_panel()), END)
    assert not sig.active
    assert "VIXCLS" in sig.zscores


def test_two_series_over_threshold_activates():
    sig = market_signal(AsOfPanel(make_panel({"VIXCLS": 1.01, "DEXKOUS": 1.01})), END)
    assert set(sig.triggered) >= {"VIXCLS", "DEXKOUS"}
    assert sig.active


def test_single_moderate_series_does_not_activate():
    panel = make_panel({"VIXCLS": 1.0035})  # 약 3.5σ
    sig = market_signal(AsOfPanel(panel), END)
    assert sig.triggered == ["VIXCLS"]
    assert not sig.active


def test_single_extreme_series_activates():
    sig = market_signal(AsOfPanel(make_panel({"VIXCLS": 1.05})), END)
    assert abs(sig.zscores["VIXCLS"]) >= 4
    assert sig.active


def test_credit_spread_falls_back_when_primary_history_short():
    panel = make_panel()
    panel["BAMLH0A0HYM2"] = calm_series(99, n=50)  # 이력 부족
    sig = market_signal(AsOfPanel(panel), END)
    assert "BAA10Y" in sig.zscores and "BAMLH0A0HYM2" not in sig.zscores

    panel["BAMLH0A0HYM2"] = calm_series(99, n=400)
    sig = market_signal(AsOfPanel(panel), END)
    assert "BAMLH0A0HYM2" in sig.zscores and "BAA10Y" not in sig.zscores


def test_stale_series_is_ignored():
    panel = make_panel()
    panel["DEXKOUS"] = panel["DEXKOUS"].iloc[:-10]
    assert "DEXKOUS" not in market_signal(AsOfPanel(panel), END).zscores


# ---------- 누수 방지 ----------


def test_future_access_raises_in_backtest():
    view = AsOfPanel(make_panel(), as_of=date(2024, 6, 3))
    with pytest.raises(FutureDataError):
        view.series("VIXCLS", date(2024, 6, 4))
    with pytest.raises(FutureDataError):
        market_signal(view, date(2024, 6, 10))


def test_future_data_does_not_change_backtest_result():
    as_of = date(2024, 6, 3)
    calm = make_panel()
    shocked = make_panel({"VIXCLS": 1.5, "DEXKOUS": 1.5})  # 마지막 날(as_of 이후)만 다름
    a = market_signal(AsOfPanel(calm, as_of=as_of), as_of)
    b = market_signal(AsOfPanel(shocked, as_of=as_of), as_of)
    assert a.zscores == b.zscores


def test_card_not_visible_before_event_date():
    events = [make_event("svb_2023", date(2023, 3, 10))]
    assert not card_news_signal(events, date(2023, 3, 9)).active
    assert card_news_signal(events, date(2023, 3, 10)).clusters[0].key == "svb_2023"
    assert not card_news_signal(events, date(2023, 3, 10) + timedelta(days=14)).active


# ---------- 등급·병합 ----------


def _market(active: bool) -> MarketSignal:
    return MarketSignal(as_of=END, zscores={}, triggered=[], active=active)


def _news(*keys: str) -> NewsSignal:
    return NewsSignal(as_of=END, clusters=[NewsCluster(key=k, label=k) for k in keys])


@pytest.mark.parametrize(
    "market,news,expected",
    [(True, ("x",), AlertLevel.ALERT), (True, (), AlertLevel.WATCH), (False, ("x",), AlertLevel.WATCH), (False, (), AlertLevel.NONE)],
)
def test_grade(market, news, expected):
    assert grade(_market(market), _news(*news)) == expected


def _alert(d: date, key: str) -> SentinelResult:
    return SentinelResult(as_of=d, level=AlertLevel.ALERT, market=_market(True), news=_news(key))


def test_same_cluster_within_72h_is_merged():
    d = date(2023, 3, 10)
    merged = merge_alerts([_alert(d, "a"), _alert(d + timedelta(days=1), "a"), _alert(d + timedelta(days=3), "a")], 72)
    assert len(merged) == 1 and merged[0].count == 3


def test_gap_over_72h_or_other_cluster_is_separate():
    d = date(2023, 3, 10)
    merged = merge_alerts([_alert(d, "a"), _alert(d + timedelta(days=4), "a"), _alert(d, "b")], 72)
    assert sorted((m.key, m.count) for m in merged) == [("a", 1), ("a", 1), ("b", 1)]


# ---------- 라이브 B (GDELT) ----------


def test_cluster_titles_groups_similar():
    titles = ["Bank run hits regional lender", "Regional lender bank run deepens", "Oil prices rise"]
    groups = cluster_titles(titles, 0.3)
    assert sorted(groups[0]) == [0, 1]


class FakeGdelt:
    def __init__(self, spike: bool, n_domains: int):
        self.spike, self.n_domains = spike, n_domains

    def daily_volume(self, query):
        idx = pd.date_range(end=pd.Timestamp(END), periods=40, freq="D")
        vals = [10.0 + (i % 3) for i in range(40)]
        if self.spike and "bank run" in query:
            vals[-1] = 100.0
        return pd.Series(vals, index=idx)

    def articles(self, query, timespan="1d"):
        now = datetime(2024, 6, 28, tzinfo=timezone.utc)
        return [Article(title=f"Bank run hits lender {i % 2}", url=f"https://s{i}.com/a", domain=f"s{i}.com", seen=now)
                for i in range(self.n_domains)]


def test_live_news_requires_volume_spike_and_sources():
    sig = live_news_signal(FakeGdelt(spike=True, n_domains=25), END)
    assert [c.event_type for c in sig.clusters] == ["banking_stress"]
    assert sig.clusters[0].n_sources == 25
    assert not live_news_signal(FakeGdelt(spike=True, n_domains=5), END).active
    assert not live_news_signal(FakeGdelt(spike=False, n_domains=25), END).active


def test_gdelt_client_parses_responses():
    import httpx

    from app.data.gdelt import GdeltClient

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == '("a" OR "b")'
        if request.url.params["mode"] == "timelinevolraw":
            return httpx.Response(200, json={"timeline": [{"data": [
                {"date": "20240627T100000Z", "value": 2}, {"date": "20240627T110000Z", "value": 3},
                {"date": "20240628T100000Z", "value": 7}]}]})
        return httpx.Response(200, json={"articles": [
            {"url": "https://x.com/1", "title": "t", "seendate": "20240628T010000Z", "domain": "x.com"}]})

    client = GdeltClient(http=httpx.Client(transport=httpx.MockTransport(handler)), interval_sec=0)
    vol = client.daily_volume('"a" OR "b"')
    assert vol.tolist() == [5.0, 7.0]
    arts = client.articles('"a" OR "b"')
    assert arts[0].domain == "x.com"


def test_live_news_records_query_errors():
    class Failing(FakeGdelt):
        def daily_volume(self, query):
            raise RuntimeError("429")

    sig = live_news_signal(Failing(spike=True, n_domains=25), END)
    assert not sig.active and len(sig.errors) == 8
