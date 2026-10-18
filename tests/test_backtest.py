from datetime import date

import numpy as np
import pandas as pd

from app.agents.sentinel import AsOfPanel, market_signal
from app.backtest import event_metrics, market_active_days, precision_recall
from app.schemas import Label
from app.services import load_saved_briefing, market_panel


def test_precision_recall_edge_cases():
    assert precision_recall(set(), set()) == (1.0, 1.0)
    assert precision_recall({"a", "b"}, {"a"}) == (0.5, 1.0)
    assert precision_recall(set(), {"a"}) == (None, 0.0)
    assert precision_recall({"a"}, set()) == (0.0, None)


def test_event_metrics_with_label():
    b = load_saved_briefing("svb_2023")
    top1 = b.match.doc_fits[0].doc_id
    not_app = [j.clause_id for f in b.match.doc_fits for j in f.judgments if j.verdict.value == "not_applicable"][:2]
    node = b.exposure_top[0].nodes[1]
    label = Label(event_id="svb_2023", reaction_date=date(2023, 3, 13), expected_docs=[top1, "PB-NOPE"],
                  expected_inapplicable_clauses=not_app, expected_gap_channels=[], expected_exposure_paths=[node, "C-NOPE"])
    m = event_metrics(b, label, date(2023, 3, 10))
    assert m["lead_time"] == 3
    assert m["doc_top3_hit"] == 0.5
    assert m["clause_recall"] == 1.0
    assert m["path_recall"] == 0.5
    if not b.match.gaps:
        assert (m["gap_precision"], m["gap_recall"]) == (1.0, 1.0)


def test_unlabeled_metrics_are_none():
    m = event_metrics(load_saved_briefing("svb_2023"), None, None)
    assert m["doc_top3_hit"] is None and m["labeled"] is False


def test_vectorized_market_signal_matches_sentinel():
    panel = market_panel()
    days = pd.bdate_range("2008-09-01", "2008-10-15").append(pd.bdate_range("2017-10-02", "2017-10-20"))
    vec = market_active_days(panel, days)
    for d in days:
        assert bool(vec[d]) == market_signal(AsOfPanel(panel, as_of=d.date()), d.date()).active
