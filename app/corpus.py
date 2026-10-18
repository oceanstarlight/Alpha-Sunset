"""저장소에 커밋된 코퍼스(data/) 로더. 모든 로더는 스키마 검증을 거친다."""

from __future__ import annotations

import json
from pathlib import Path

from app.config import ROOT_DIR
from app.schemas import CalmWindow, Event, Label, Playbook, Portfolio

DATA_DIR = ROOT_DIR / "data"


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _files(subdir: str, pattern: str = "*.json") -> list[Path]:
    # `_`로 시작하는 파일은 템플릿
    return sorted(p for p in (DATA_DIR / subdir).glob(pattern) if not p.name.startswith("_"))


def load_playbooks() -> list[Playbook]:
    return [Playbook.model_validate(_load(p)) for p in _files("playbooks")]


def load_events() -> list[Event]:
    return [Event.model_validate(_load(p)) for p in _files("events") if not p.name.startswith("calm_")]


def load_calm_windows() -> list[CalmWindow]:
    return [CalmWindow.model_validate(_load(p)) for p in _files("events", "calm_*.json")]


def load_portfolio() -> Portfolio:
    return Portfolio.model_validate(_load(DATA_DIR / "portfolio.json"))


UNFILLED_DATE = "YYYY-MM-DD"


def load_labels() -> list[Label]:
    """작성된 라벨만 반환한다. reaction_date가 비어 있는(YYYY-MM-DD) 빈 틀은 건너뛴다."""
    raw = [_load(p) for p in _files("labels")]
    return [Label.model_validate(d) for d in raw if d.get("reaction_date") != UNFILLED_DATE]


def check_label_refs(label: Label, playbooks: list[Playbook], events: list[Event], portfolio: Portfolio) -> list[str]:
    """라벨이 존재하지 않는 문서·조항·사건·노드를 가리키는지 확인한다. 문제 목록을 반환."""
    doc_ids = {p.doc_id for p in playbooks}
    clause_ids = {c.clause_id for p in playbooks for c in p.clauses}
    node_ids = {n.id for n in portfolio.nodes}
    errors = []
    if label.event_id not in {e.id for e in events}:
        errors.append(f"알 수 없는 event_id: {label.event_id}")
    errors += [f"알 수 없는 doc_id: {d}" for d in label.expected_docs if d not in doc_ids]
    errors += [f"알 수 없는 clause_id: {c}" for c in label.expected_inapplicable_clauses if c not in clause_ids]
    errors += [f"알 수 없는 노드 id: {n}" for n in label.expected_exposure_paths if n not in node_ids]
    return errors
