"""P9 Learner ON/OFF 비교 (사전 등록 v4) → data/backtest/learner_results.json.

커밋된 브리핑의 MatchResult를 재사용하고(LLM 재호출 없음), 사건 처리 뒤 라벨 기반 시뮬레이션 피드백을
sandbox.db shadow_log(mode=sim)에 기록한다. 결과는 '시뮬레이션 기반'이며 라벨 순환 위험이 있다.
사용: python -m scripts.run_learner_sim
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from app.agents import learner
from app.agents.matcher import protected_only
from app.backtest import mean_or_none
from app.config import ROOT_DIR
from app.corpus import load_events, load_labels, load_playbooks
from app.db import connect
from app.schemas import Briefing

BT = ROOT_DIR / "data" / "backtest"
OUT = BT / "learner_results.json"
VIRTUAL_START = date(2000, 1, 3)  # 반복 시뮬레이션 가상 시간 기준 (사건마다 60일 간격)


def top3_hit(doc_ids: list[str], expected: list[str]) -> float | None:
    return sum(d in doc_ids[:3] for d in expected) / len(expected) if expected else None


def record_feedback(event_id: str, event_type: str, fits, ranked: list[str], expected: list[str], ts: date) -> None:
    conn = connect("sandbox")
    with conn:
        for f in fits:
            cited = int(f.n_applicable + f.n_partial > 0)
            fb = "useful" if f.doc_id in expected else ("not_fit" if f.doc_id in ranked[:3] else None)
            conn.execute(
                "INSERT INTO shadow_log (event_id, doc_id, event_type, cited, rank, feedback, mode, ts) VALUES (?, ?, ?, ?, ?, ?, 'sim', ?)",
                (event_id, f.doc_id, event_type, cited, ranked.index(f.doc_id) + 1, fb, ts.isoformat()),
            )
    conn.close()


def clear_sim() -> None:
    conn = connect("sandbox")
    with conn:
        conn.execute("DELETE FROM shadow_log WHERE mode = 'sim'")
    conn.close()


def run_pass(schedule: list[tuple[str, date]], briefings: dict, labels: dict, clauses: dict, protected: set) -> list[dict]:
    rows = []
    for event_id, as_of in schedule:
        b = briefings[event_id]
        fits = b.match.doc_fits
        expected = labels[event_id].expected_docs
        off = [f.doc_id for f in fits]
        pri = learner.compute_priority(off, b.event.type.value, as_of, "sim", protected)
        tail = {f.doc_id for f in fits if protected_only(f, clauses)}
        on = [f.doc_id for f in learner.rerank(fits, pri, tail)]
        rows.append({"event_id": event_id, "as_of": as_of.isoformat(), "top3_off": off[:3], "top3_on": on[:3],
                     "hit_off": top3_hit(off, expected), "hit_on": top3_hit(on, expected),
                     "priority_top": sorted(((d, p.priority) for d, p in pri.items()), key=lambda x: -x[1])[:3]})
        record_feedback(event_id, b.event.type.value, fits, on, expected, as_of)
    return rows


def main() -> None:
    labels = {lb.event_id: lb for lb in load_labels()}
    events = sorted(load_events(), key=lambda e: e.date)
    briefings = {e.id: Briefing.model_validate(json.loads((BT / "briefings" / f"{e.id}.json").read_text(encoding="utf-8"))["briefing"])
                 for e in events}
    clauses = {c.clause_id: c for p in load_playbooks() for c in p.clauses}
    protected = {c.doc_id for c in clauses.values() if c.protected}

    clear_sim()
    pass_a = run_pass([(e.id, e.date) for e in events], briefings, labels, clauses, protected)

    clear_sim()
    schedule = [(e.id, VIRTUAL_START + timedelta(days=60 * k)) for k, e in enumerate(events + events)]
    pass_b = run_pass(schedule, briefings, labels, clauses, protected)
    second = pass_b[len(events):]
    clear_sim()

    def delta(rows):
        on, off = mean_or_none([r["hit_on"] for r in rows]), mean_or_none([r["hit_off"] for r in rows])
        return None if on is None or off is None else round(on - off, 4), on, off

    da, on_a, off_a = delta(pass_a)
    db, on_b, off_b = delta(second)
    out = {"preregistration": "data/backtest/ablation/preregistration_v4_learner.json",
           "pass_A": {"description": "실제 날짜 순 1회 재생", "doc_top3_hit_off": off_a, "doc_top3_hit_on": on_a, "learner_delta": da, "events": pass_a},
           "pass_B": {"description": "같은 순서 2회 반복(가상 시간 60일 간격), 2회차로 평가", "doc_top3_hit_off": off_b, "doc_top3_hit_on": on_b,
                      "learner_delta_sim": db, "events": pass_b},
           "caveats": ["시뮬레이션 기반: 피드백은 라벨(expected_docs)에서 생성되어 순환 위험이 있다.",
                       "pass_B는 같은 사건을 반복하므로 실제 성능이 아니라 학습 메커니즘 작동 확인이다."]}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"pass A (실제 순서 1회): OFF {off_a}  ON {on_a}  delta {da}")
    print(f"pass B (반복 2회차):    OFF {off_b}  ON {on_b}  delta {db}")
    for r in second:
        if r["top3_on"] != r["top3_off"]:
            print(f"  {r['event_id']}: {r['top3_off']} → {r['top3_on']}")


if __name__ == "__main__":
    main()
