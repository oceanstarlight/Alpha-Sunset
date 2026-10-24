"""Learner (알파 썬셋): 인용·피드백 이력으로 문서 검색 우선순위를 조정한다 (plans.md 5.4).

- 문서를 삭제·폐기하지 않고 순위 보정만 한다. protected 문서는 priority 하한 0.5로 항상 후보에 남는다.
- 입력은 shadow_log만, 모드(live|backtest|sim)별로 분리 집계한다. 라이브 점수에는 sandbox 로그가 들어가지 않는다
  (live는 live.db, backtest·sim은 sandbox.db에서만 읽는다).
- 기본 OFF. 토글 변경은 learner_toggle_log에 기록한다.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.config import get_settings, load_config
from app.db import DbMode, connect
from app.schemas import DocFit

_override: bool | None = None

MODE_DB: dict[str, DbMode] = {"live": "live", "backtest": "sandbox", "sim": "sandbox"}


def is_enabled() -> bool:
    return get_settings().learner_enabled if _override is None else _override


def set_enabled(enabled: bool, db: DbMode = "sandbox") -> None:
    global _override
    _override = enabled
    conn = connect(db)
    with conn:
        conn.execute("INSERT INTO learner_toggle_log (enabled, ts) VALUES (?, ?)",
                     (int(enabled), datetime.now(timezone.utc).isoformat()))
    conn.close()
    from app import audit

    audit.log("learner_toggle", {"enabled": enabled, "db": db})


@dataclass
class DocPriority:
    doc_id: str
    priority: float
    cite_norm: float
    fb: float
    recency: float
    explore: float
    n_cited: int
    useful: int
    not_fit: int


def _rows(mode: str, event_type: str, as_of: date | None) -> list[dict]:
    conn = connect(MODE_DB[mode])
    query = "SELECT event_id, doc_id, cited, feedback, ts FROM shadow_log WHERE mode = ? AND event_type = ?"
    params: list = [mode, event_type]
    if as_of is not None:
        query += " AND substr(ts, 1, 10) < ?"  # 기준일 이전 기록만 (시뮬레이션 시간 기준)
        params.append(as_of.isoformat())
    rows = [dict(r) for r in conn.execute(query, params)]
    conn.close()
    return rows


def compute_priority(doc_ids: list[str], event_type: str, as_of: date, mode: str = "backtest",
                     protected_docs: set[str] | None = None) -> dict[str, DocPriority]:
    cfg = load_config()["learner"]
    half_life, c, w = cfg["half_life_days"], cfg["explore_c"], cfg["weights"]
    rows = _rows(mode, event_type, as_of)

    decayed: dict[str, float] = defaultdict(float)
    last: dict[str, date] = {}
    n_cited: dict[str, int] = defaultdict(int)
    useful: dict[str, int] = defaultdict(int)
    not_fit: dict[str, int] = defaultdict(int)
    events = set()
    for r in rows:
        d = date.fromisoformat(r["ts"][:10])
        events.add(r["event_id"])
        if r["cited"]:
            decayed[r["doc_id"]] += 0.5 ** ((as_of - d).days / half_life)
            n_cited[r["doc_id"]] += 1
            last[r["doc_id"]] = max(last.get(r["doc_id"], d), d)
        if r["feedback"] == "useful":
            useful[r["doc_id"]] += 1
        elif r["feedback"] == "not_fit":
            not_fit[r["doc_id"]] += 1

    max_decayed = max(decayed.values(), default=0.0)
    n_type = len(events)
    out = {}
    for doc in doc_ids:
        cite = decayed[doc] / max_decayed if max_decayed else 0.0
        fb = (useful[doc] + 1) / (useful[doc] + not_fit[doc] + 2)
        rec = math.exp(-(as_of - last[doc]).days / half_life) if doc in last else 0.0
        explore = c * math.sqrt(math.log(n_type + 1) / (n_cited[doc] + 1))
        p = min(max(w["cite"] * cite + w["feedback"] * fb + w["recency"] * rec + explore, 0.0), 1.0)
        if protected_docs and doc in protected_docs:
            p = max(p, cfg["protected_floor"])
        out[doc] = DocPriority(doc, round(p, 4), round(cite, 4), round(fb, 4), round(rec, 4), round(explore, 4),
                               n_cited[doc], useful[doc], not_fit[doc])
    return out


def adjusted_score(fit_score: float, priority: float) -> float:
    return fit_score * (1 + load_config()["learner"]["boost"] * (priority - 0.5))


def rerank(fits: list[DocFit], priorities: dict[str, DocPriority], tail: set[str] | None = None) -> list[DocFit]:
    """final = fit × (1 + 0.3·(priority − 0.5)) 순. tail(protected 조항만 판정된 문서)은 하단 유지."""
    tail = tail or set()
    return sorted(fits, key=lambda f: (f.doc_id in tail,
                                       -adjusted_score(f.fit_score, priorities[f.doc_id].priority if f.doc_id in priorities else 0.5),
                                       -f.n_applicable, f.doc_id))
