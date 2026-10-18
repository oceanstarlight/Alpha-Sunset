import math
from datetime import date

import pytest

from app import services
from app.agents import learner
from app.db import connect
from app.schemas import ClauseJudgment, DocFit, Verdict


def log(db, rows):
    conn = connect(db)
    with conn:
        conn.executemany("INSERT INTO shadow_log (event_id, doc_id, event_type, cited, rank, feedback, mode, ts) VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.close()


def test_priority_formula_matches_plan():
    log("sandbox", [("e1", "A", "banking_stress", 1, 1, "useful", "backtest", "2023-01-01"),
                    ("e1", "B", "banking_stress", 0, 2, "not_fit", "backtest", "2023-01-01")])
    p = learner.compute_priority(["A", "B", "C"], "banking_stress", date(2023, 7, 1), "backtest")
    dt = (date(2023, 7, 1) - date(2023, 1, 1)).days
    explore_a = 0.2 * math.sqrt(math.log(2) / 2)
    expected_a = 0.4 * 1.0 + 0.4 * (2 / 3) + 0.2 * math.exp(-dt / 180) + explore_a
    assert p["A"].priority == pytest.approx(expected_a, abs=1e-3)
    assert p["B"].fb == pytest.approx(1 / 3, abs=1e-3) and p["B"].cite_norm == 0
    assert p["C"].fb == 0.5  # 이력 없음 → 사전 0.5


def test_future_and_other_type_rows_ignored():
    log("sandbox", [("e1", "A", "banking_stress", 1, 1, "useful", "backtest", "2024-01-01"),
                    ("e2", "A", "pandemic", 1, 1, "useful", "backtest", "2022-01-01")])
    p = learner.compute_priority(["A"], "banking_stress", date(2023, 1, 1), "backtest")
    assert p["A"].n_cited == 0


def test_protected_floor():
    log("sandbox", [("e1", "R", "banking_stress", 0, 9, "not_fit", "backtest", "2023-01-01")] * 5)
    p = learner.compute_priority(["R"], "banking_stress", date(2023, 2, 1), "backtest", protected_docs={"R"})
    assert p["R"].priority >= 0.5


def test_live_scores_never_use_sandbox_logs():
    log("sandbox", [("e1", "A", "banking_stress", 1, 1, "useful", "backtest", "2023-01-01"),
                    ("e1", "A", "banking_stress", 1, 1, "useful", "sim", "2023-01-01")])
    live = learner.compute_priority(["A"], "banking_stress", date(2023, 2, 1), "live")
    assert live["A"].n_cited == 0 and live["A"].useful == 0
    sim = learner.compute_priority(["A"], "banking_stress", date(2023, 2, 1), "sim")
    bt = learner.compute_priority(["A"], "banking_stress", date(2023, 2, 1), "backtest")
    assert sim["A"].n_cited == 1 and bt["A"].n_cited == 1  # 모드별 분리 집계


def _fit(doc, score):
    j = ClauseJudgment(clause_id=f"{doc}-01", verdict=Verdict.applicable, evidence_quote="x", confidence=1)
    return DocFit(doc_id=doc, fit_score=score, n_applicable=1, n_partial=0, n_not=0, n_uncertain=0, judgments=[j])


def test_rerank_boost_and_tail():
    fits = [_fit("A", 0.50), _fit("B", 0.48), _fit("R", 0.9)]
    pri = {"A": learner.DocPriority("A", 0.2, 0, 0, 0, 0, 0, 0, 0), "B": learner.DocPriority("B", 1.0, 0, 0, 0, 0, 0, 0, 0)}
    ranked = [f.doc_id for f in learner.rerank(fits, pri, tail={"R"})]
    assert ranked == ["B", "A", "R"]


def test_learner_off_means_fit_order():
    from app.agents.matcher import rank_doc_fits

    fits = [_fit("A", 0.3), _fit("B", 0.7)]
    assert [f.doc_id for f in rank_doc_fits(fits, learner_enabled=False)] == ["B", "A"]


def test_toggle_is_logged():
    assert services.learner_enabled() is False
    services.set_learner_enabled(True)
    assert services.learner_enabled() is True
    services.set_learner_enabled(False)
    conn = connect("sandbox")
    assert [tuple(r) for r in conn.execute("SELECT enabled FROM learner_toggle_log ORDER BY id")] == [(1,), (0,)]
    conn.close()
