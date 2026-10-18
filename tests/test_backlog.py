"""사전 등록 v2 항목: 자금 흐름 신호 C, 등급 v2, 공백 규칙 v2, protected 순위, 핵심 경로, 기계적 대응일."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.agents.matcher import covers, find_gaps, rank_doc_fits, build_doc_fits
from app.agents.sentinel import AsOfPanel, FlowSignal, MarketSignal, NewsCluster, NewsSignal, flow_signal, grade
from app.backtest import flow_active_days, reaction_date_flow
from app.schemas import AlertLevel, Channel, Clause, ClauseJudgment, Duration, Event, EventType, Premises, Verdict


def weekly(n=120, shock=None, end="2024-06-26"):
    rng = np.random.default_rng(1)
    idx = pd.date_range(end=end, periods=n, freq="W-WED")
    s = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0, 0.002, n))), index=idx)
    if shock:
        s.iloc[-1] = s.iloc[-2] * shock
    return s


def test_flow_signal_respects_publication_lag():
    panel = {"WMTSECL1": weekly(shock=1.10)}  # 마지막 관측(6/26)에 급변, 공표 시차 3일
    assert not flow_signal(AsOfPanel(panel, as_of=date(2024, 6, 28)), date(2024, 6, 28)).active
    sig = flow_signal(AsOfPanel(panel, as_of=date(2024, 7, 1)), date(2024, 7, 1))
    assert sig.active and sig.triggered == ["WMTSECL1"]


def test_vectorized_flow_matches_signal():
    panel = {"WMTSECL1": weekly(shock=1.10), "DPSACBW027SBOG": weekly()}
    days = pd.bdate_range("2024-06-17", "2024-07-12")
    vec = flow_active_days(panel, days)
    for d in days:
        assert bool(vec[d]) == flow_signal(AsOfPanel(panel, as_of=d.date()), d.date()).active


def _m(a): return MarketSignal(as_of=date(2024, 1, 1), zscores={}, triggered=[], active=a)
def _f(a): return FlowSignal(as_of=date(2024, 1, 1), zscores={}, triggered=[], active=a)
def _n(a): return NewsSignal(as_of=date(2024, 1, 1), clusters=[NewsCluster(key="x", label="x")] if a else [])


@pytest.mark.parametrize("a,b,c,expected", [
    (False, True, True, AlertLevel.ALERT), (True, True, False, AlertLevel.ALERT),
    (False, False, True, AlertLevel.WATCH), (False, True, False, AlertLevel.WATCH), (False, False, False, AlertLevel.NONE)])
def test_grade_v2(a, b, c, expected):
    assert grade(_m(a), _n(b), _f(c)) == expected


EVENT = Event(id="e", title="e", date=date(2023, 3, 10), summary="", type=EventType.banking_stress,
              channels=[Channel.liquidity, Channel.equity_vol], duration=Duration.weeks, severity=3)


def _clause(cid, types, channels, protected=False):
    return Clause(clause_id=cid, doc_id=cid.split("-")[0], text="t", owner_role="r",
                  premises=Premises(event_types=types, channels=channels),
                  protected=protected, protected_reason="regulatory" if protected else None)


def _j(cid, v):
    return ClauseJudgment(clause_id=cid, verdict=v, evidence_quote="" if v == Verdict.uncertain else "t", confidence=0.9)


def test_gap_rule_v2_partial_needs_matching_event_type():
    clauses = {"A-01": _clause("A-01", [EventType.pandemic], [Channel.liquidity]),
               "B-01": _clause("B-01", [EventType.banking_stress], [Channel.equity_vol])}
    js = [_j("A-01", Verdict.partial), _j("B-01", Verdict.partial)]
    assert not covers(js[0], clauses["A-01"], EVENT) and covers(js[1], clauses["B-01"], EVENT)
    assert find_gaps(EVENT, js, clauses) == [Channel.liquidity]


def test_protected_only_docs_ranked_last():
    clauses = {"R-01": _clause("R-01", [], [], protected=True), "A-01": _clause("A-01", [EventType.banking_stress], [])}
    fits = build_doc_fits([_j("R-01", Verdict.applicable), _j("A-01", Verdict.partial)], clauses)
    ranked = rank_doc_fits(fits, learner_enabled=False, clauses=clauses)
    assert [f.doc_id for f in ranked] == ["A", "R"]


def test_reaction_date_flow_defaults_to_event_date_when_calm():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2022-01-03", "2024-06-28")
    panel = {"VIXCLS": pd.Series(20 * np.exp(np.cumsum(rng.normal(0, 0.001, len(idx)))), index=idx)}
    assert reaction_date_flow(panel, date(2024, 6, 3)) == date(2024, 6, 3)


def test_core_paths_on_committed_holdings():
    from app.agents.exposure import compute_exposure, region_tags
    from app.corpus import load_events, load_portfolio

    ru = next(e for e in load_events() if e.id == "ru_ua_2022").as_of_view()
    rep = compute_exposure(ru, load_portfolio(), None)
    specific = set(ru.regions) - {"GLOBAL"}
    top_keys = {tuple(p.nodes) for p in rep.paths}
    assert rep.core_paths
    for p in rep.core_paths:
        assert tuple(p.nodes) not in top_keys
        assert region_tags(p.nodes[-1].split(" · ")[0].split("/")) & specific
