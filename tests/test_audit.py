"""B5: 영구 감사 로그 (추가 전용 + 해시 체인)."""

import json

from app import audit


def test_append_builds_chain_and_verifies():
    a = audit.append("approval", {"run_id": "r1", "decision": "approve"}, actor="kim")
    b = audit.append("feedback", {"run_id": "r1", "doc_id": "PB-BANK", "label": "useful"}, actor="kim")
    assert a["seq"] == 1 and a["prev_hash"] == audit.GENESIS
    assert b["seq"] == 2 and b["prev_hash"] == a["hash"]
    v = audit.verify("app")
    assert v.ok and v.n == 2
    assert audit.sources() == ["app"]


def _rewrite(lines):
    audit.path_for("app").write_text("".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in lines),
                                     encoding="utf-8")


def test_tampered_content_detected():
    for i in range(3):
        audit.append("feedback", {"i": i})
    rows = audit.read("app")
    rows[1]["data"]["i"] = 99
    _rewrite(rows)
    v = audit.verify("app")
    assert not v.ok and v.bad_seq == 2 and "변조" in v.reason


def test_deleted_line_detected():
    for i in range(3):
        audit.append("feedback", {"i": i})
    rows = audit.read("app")
    _rewrite([rows[0], rows[2]])
    v = audit.verify("app")
    assert not v.ok and v.bad_seq == 3


def test_rehashed_line_still_breaks_next_link():
    for i in range(3):
        audit.append("feedback", {"i": i})
    rows = audit.read("app")
    rows[1]["data"]["i"] = 99
    rows[1]["hash"] = audit._digest(rows[1])  # 변조 후 해시까지 다시 계산해도
    _rewrite(rows)
    v = audit.verify("app")
    assert not v.ok and v.bad_seq == 3 and "앞 줄" in v.reason


def test_sources_are_separate_files():
    audit.append("signal_run", {"level": "WATCH"}, source="collect_signals")
    audit.append("kr_run", {"level": "NONE"}, source="monitor_kr")
    assert audit.sources() == ["collect_signals", "monitor_kr"]
    assert all(audit.verify(s).ok for s in audit.sources())


def test_log_never_raises(monkeypatch):
    monkeypatch.setattr(audit, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    audit.log("x")  # 예외 없이 통과


def test_services_record_approval_and_feedback_are_audited():
    from app import services
    from app.schemas import Feedback

    b = services.load_saved_briefing("svb_2023")
    services.record_approval(b, "approve", "kim", note="확인")
    services.submit_feedback(Feedback(run_id=b.run_id, doc_id=b.match.doc_fits[0].doc_id, label="useful", user_id="kim"), b)
    rows = audit.read("app")
    assert [r["action"] for r in rows] == ["approval", "feedback"]
    assert rows[0]["actor"] == "kim" and rows[1]["data"]["rank"] == 1
    assert audit.verify("app").ok


def test_learner_toggle_is_audited():
    from app.agents import learner

    learner.set_enabled(True)
    assert audit.read("app")[-1]["action"] == "learner_toggle"
