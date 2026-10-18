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
    market_signal,
    merge_alerts,
)
from app.data.korea import NewsItem
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


# ---------- 라이브 B (Google 뉴스 RSS) ----------


def test_cluster_titles_groups_similar():
    titles = ["Bank run hits regional lender", "Regional lender bank run deepens", "Oil prices rise"]
    groups = cluster_titles(titles, 0.3)
    assert sorted(groups[0]) == [0, 1]


NOW = datetime(2024, 6, 28, 12, tzinfo=timezone.utc)


def _items(n, n_src, title="Bank run hits lender"):
    return [NewsItem(f"{title} {i % 2}", f"https://s{i}.com/a", f"src{i % n_src}", NOW, "google") for i in range(n)]


def _history(event_type="banking_stress", n=10, days=25):
    return [{"ts": (NOW - timedelta(days=d)).isoformat(), "event_type": event_type, "n_articles": n + d % 3, "n_sources": 8}
            for d in range(1, days + 1)]


def test_rss_news_requires_spike_vs_baseline_and_sources():
    from app.agents.sentinel import rss_news_signal

    sig, rows, obs = rss_news_signal({"banking_stress": _items(60, 25)}, _history(), NOW)
    assert [c.event_type for c in sig.clusters] == ["banking_stress"] and obs["banking_stress"]["z"] > 3
    assert rows[0]["n_articles"] == 60  # 이번 관측은 기준선 이력에 쌓인다
    assert not rss_news_signal({"banking_stress": _items(60, 10)}, _history(), NOW)[0].active  # 언론사 20곳 미만
    assert not rss_news_signal({"banking_stress": _items(11, 25)}, _history(), NOW)[0].active  # 평소 수준


def test_rss_news_unavailable_while_baseline_accumulates():
    from app.agents.sentinel import rss_news_signal

    sig, _, obs = rss_news_signal({"banking_stress": _items(60, 25)}, _history(days=5), NOW)
    assert not sig.active and "기준선 축적 중" in sig.errors[0] and obs["banking_stress"]["baseline_points"] == 5


def test_fetch_rss_topics_records_failures():
    from app.agents.sentinel import fetch_rss_topics

    class Half:
        def search(self, query, since):
            if "bank run" in query:
                raise RuntimeError("timeout")
            assert " OR " in query and not query.startswith("(")
            return _items(3, 3)

    arts, errors = fetch_rss_topics(Half(), NOW)
    assert "banking_stress" not in arts and len(arts) == 7 and "RSS 실패" in errors[0]


def test_signal_status_partial_and_unavailable():
    assert NewsSignal(as_of=END, errors=["x"], n_queries=8).status == "partial"
    assert NewsSignal(as_of=END, errors=["x"] * 8, n_queries=8).status == "unavailable"
    assert NewsSignal(as_of=END, n_queries=8).status == "ok"


def test_explain_gives_cause_evidence_result_for_every_stage():
    from app.agents.sentinel import explain

    m = MarketSignal(as_of=END, zscores={"VIXCLS": 3.1, "BAA10Y": 2.7, "DGS10": 0.2}, triggered=["VIXCLS", "BAA10Y"], active=True)
    n = NewsSignal(as_of=END, clusters=[NewsCluster(key="k", label="Bank run", event_type="banking_stress",
                                                    n_articles=40, n_sources=25, z=4.2)], n_queries=8)
    chain = explain(SentinelResult(as_of=END, level=grade(m, n), market=m, news=n))
    assert [c["단계"] for c in chain] == ["시장 신호(A)", "사건 신호(B)", "종합 등급"]
    assert all(set(c) == {"단계", "원인", "근거", "결과"} and c["원인"] and c["근거"] for c in chain)
    assert "VIXCLS" in chain[0]["원인"] and "언론사 25곳" in chain[1]["근거"] and chain[2]["결과"].startswith("ALERT")
    failed = NewsSignal(as_of=END, clusters=[], errors=["x"] * 8, n_queries=8)
    assert explain(SentinelResult(as_of=END, level=grade(m, failed), market=m, news=failed))[1]["결과"] == "판단 불가"
