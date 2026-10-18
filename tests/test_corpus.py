from datetime import date

import pytest
from pydantic import ValidationError

from app.corpus import (
    check_label_refs,
    load_calm_windows,
    load_events,
    load_labels,
    load_playbooks,
    load_portfolio,
)
from app.schemas import Label, PortfolioNode
from scripts.gen_playbooks import check as check_playbooks

BACKTEST_EVENTS = {"gfc_2008", "covid_2020", "ru_ua_2022", "legoland_2022", "svb_2023", "tariff_2025"}


def test_playbooks_valid_and_synthetic():
    playbooks = load_playbooks()
    assert len(playbooks) == 12
    assert all(p.synthetic for p in playbooks)
    assert check_playbooks() == []


def test_protected_documents_exist():
    protected = {c.protected_reason for p in load_playbooks() for c in p.clauses if c.protected}
    assert protected == {"regulatory", "insurance"}


def test_backtest_events_have_sources():
    events = load_events()
    assert {e.id for e in events} == BACKTEST_EVENTS
    assert all(e.sources for e in events)


def test_calm_windows():
    calm = load_calm_windows()
    assert len(calm) == 3
    assert all(c.start < c.end for c in calm)


def test_portfolio_synthetic_and_uncertainty_by_kind():
    portfolio = load_portfolio()
    assert portfolio.synthetic
    expected = {"direct": 0.0, "manager": 0.3, "counterparty": 0.5}
    assert all(n.uncertainty == expected[n.kind] for n in portfolio.nodes)
    assert sum(n.kind == "manager" for n in portfolio.nodes) == 6
    assert sum(n.kind == "counterparty" for n in portfolio.nodes) == 5


def test_manager_requires_proxy_fund():
    with pytest.raises(ValidationError):
        PortfolioNode(id="M-X", name="x", kind="manager", instrument="fund", weight=0.1, uncertainty=0.3)


def test_labels_reference_existing_items():
    playbooks, events, portfolio = load_playbooks(), load_events(), load_portfolio()
    for label in load_labels():
        assert check_label_refs(label, playbooks, events, portfolio) == []


def test_label_ref_check_catches_unknown_ids():
    label = Label(
        event_id="svb_2023", reaction_date=date(2023, 3, 10),
        expected_docs=["PB-NOPE"], expected_inapplicable_clauses=["PB-LIQ-99"], expected_exposure_paths=["M-NOPE"],
    )
    errors = check_label_refs(label, load_playbooks(), load_events(), load_portfolio())
    assert len(errors) == 3


def test_as_of_view_removes_hindsight():
    for e in load_events():
        v = e.as_of_view()
        assert e.summary_as_of and v.summary == e.summary_as_of
        assert v.entities == e.entities_as_of
    svb = next(e for e in load_events() if e.id == "svb_2023").as_of_view()
    assert "Signature Bank" not in svb.entities and "3월 12일" not in svb.summary
