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
    assert sig.status == "unavailable"  # 전부 실패 = '사건 없음'이 아니라 '판단 불가'


def test_news_status_partial_and_ok():
    class HalfFailing(FakeGdelt):
        def daily_volume(self, query):
            if "bank run" in query:
                raise RuntimeError("Server disconnected")
            return super().daily_volume(query)

    assert live_news_signal(HalfFailing(spike=False, n_domains=25), END).status == "partial"
    assert live_news_signal(FakeGdelt(spike=False, n_domains=25), END).status == "ok"


def test_gdelt_client_retries_disconnect_and_429():
    import httpx

    from app.data.gdelt import GdeltClient

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if len(calls) == 2:
            return httpx.Response(429, text="Please limit requests")
        return httpx.Response(200, json={"articles": [
            {"url": "https://x.com/1", "title": "t", "seendate": "20240628T010000Z", "domain": "x.com",
             "sourcecountry": "South Korea"}]})

    client = GdeltClient(http=httpx.Client(transport=httpx.MockTransport(handler)), interval_sec=0)
    arts = client.articles("x")
    assert len(calls) == 3 and arts[0].source_country == "South Korea"

    always = GdeltClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))), interval_sec=0)
    with pytest.raises(RuntimeError, match="4회 시도 실패"):
        always.articles("x")


def test_explain_gives_cause_evidence_result_for_every_stage():
    from app.agents.sentinel import explain

    m = MarketSignal(as_of=END, zscores={"VIXCLS": 3.1, "BAA10Y": 2.7, "DGS10": 0.2}, triggered=["VIXCLS", "BAA10Y"], active=True)
    n = NewsSignal(as_of=END, clusters=[NewsCluster(key="k", label="Bank run", event_type="banking_stress",
                                                    n_articles=40, n_sources=25, z=4.2)], n_queries=8)
    chain = explain(SentinelResult(as_of=END, level=grade(m, n), market=m, news=n))
    assert [c["단계"] for c in chain] == ["시장 신호(A)", "사건 신호(B)", "종합 등급"]
    assert all(set(c) == {"단계", "원인", "근거", "결과"} and c["원인"] and c["근거"] for c in chain)
    assert "VIXCLS" in chain[0]["원인"] and "출처 25곳" in chain[1]["근거"] and chain[2]["결과"].startswith("ALERT")
    failed = NewsSignal(as_of=END, clusters=[], errors=["x"] * 8, n_queries=8)
    assert explain(SentinelResult(as_of=END, level=grade(m, failed), market=m, news=failed))[1]["결과"] == "판단 불가"


def test_topics_state_builds_signal_with_staleness():
    from app.agents.sentinel import news_signal_from_topics, news_topic

    now = datetime(2024, 6, 28, 12, tzinfo=timezone.utc)
    hit = news_topic(FakeGdelt(spike=True, n_domains=25), "banking_stress", '"bank run" OR "bank failure"', END)
    assert hit["cluster"] and hit["z"] > 3
    state = {
        "banking_stress": {"ok_at": (now - timedelta(hours=2)).isoformat(), "result": hit},
        "credit_event": {"ok_at": (now - timedelta(hours=40)).isoformat(), "result": {"cluster": None}, "error": "429"},
    }
    sig = news_signal_from_topics(state, END, now)
    assert [c.event_type for c in sig.clusters] == ["banking_stress"]
    assert sig.status == "partial" and any("40시간 전" in e for e in sig.errors)
    assert any("성공 이력 없음" in e for e in sig.errors)  # 한 번도 못 받은 주제


def test_collector_skips_fresh_topics_and_respects_budget():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("collect", Path(__file__).resolve().parent.parent / "scripts" / "collect_signals.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    now = datetime(2024, 6, 28, 12, tzinfo=timezone.utc)
    calls = []

    class Counting(FakeGdelt):
        def daily_volume(self, query):
            calls.append(query)
            return super().daily_volume(query)

    state = {"banking_stress": {"ok_at": (now - timedelta(hours=1)).isoformat(), "result": {"cluster": None}}}
    out = mod.collect_topics(Counting(spike=False, n_domains=25), state, END, now, budget_sec=3600)
    assert len(calls) == 7 and all(v.get("ok_at") for v in out.values())  # 1시간 전 성공한 주제는 다시 안 받음
    calls.clear()
    mod.collect_topics(Counting(spike=False, n_domains=25), {}, END, now, budget_sec=-1)
    assert calls == []  # 예산 0이면 다음 실행으로 미룸


def test_combined_coverage_single_request():
    from app import geo

    class One(FakeGdelt):
        n = 0

        def articles(self, query, timespan="1d"):
            One.n += 1
            assert query.startswith("(") and "bank run" in query and "tariff" in query
            now = datetime(2024, 6, 28, tzinfo=timezone.utc)
            return [Article("Tariff war escalates", "u1", "a.com", now, "United States"),
                    Article("Bank run fears", "u2", "b.com", now, "Germany")]

    cov = geo.gdelt_coverage_combined(One(spike=False, n_domains=1))
    assert One.n == 1 and cov["countries"] == {"United States": 1, "Germany": 1}
    assert cov["by_query"]["trade_policy"]["n_articles"] == 1 and cov["by_query"]["banking_stress"]["n_articles"] == 1


def test_quick_news_signal_uses_two_requests():
    from app.agents.sentinel import quick_news_signal

    calls = []

    class Two(FakeGdelt):
        def daily_volume(self, query):
            calls.append("vol")
            return super().daily_volume(query)  # 결합 쿼리에 "bank run" 포함 → 급증

        def articles(self, query, timespan="1d"):
            calls.append("art")
            return super().articles(query, timespan)

    sig, info = quick_news_signal(Two(spike=True, n_domains=25), END)
    assert calls == ["vol", "art"]
    assert [c.event_type for c in sig.clusters] == ["banking_stress"] and info["combined_z"] > 3
    assert sig.status == "ok" and info["by_topic"]["banking_stress"]["n_sources"] == 25

    class Down(FakeGdelt):
        def daily_volume(self, query):
            raise RuntimeError("429")

        def articles(self, query, timespan="1d"):
            raise RuntimeError("429")

    sig, info = quick_news_signal(Down(spike=False, n_domains=1), END)
    assert sig.status == "unavailable" and info["coverage"]["status"] == "unavailable"
