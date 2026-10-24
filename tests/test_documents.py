import json
from pathlib import Path

from app.ingest.documents import (
    ClauseAttrs,
    DocParse,
    RawClause,
    _pdf_lines,
    ingest_document,
    split_clauses,
    validate_attrs,
)

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "ingest" / "doc_samples"
TRUTH = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))["docs"]


def _n(s):
    return "".join(s.split())


def test_docx_and_pdf_samples_recover_all_clauses_and_owners_without_llm():
    for fname, doc in (("PB-BANK.docx", "PB-BANK"), ("PB-LIQ.pdf", "PB-LIQ")):
        r = ingest_document((SAMPLES / fname).read_bytes(), fname)
        got = r.playbook.clauses
        assert len(got) == len(TRUTH[doc])
        for t in TRUTH[doc]:
            hit = next(c for c in got if _n(t["text"]) in _n(c.text))  # 원문 그대로 보존
            assert hit.owner_role == t["owner_role"]
        assert r.playbook.doc_id == f"UP-{doc}" and not r.playbook.synthetic


def test_clause_split_patterns_and_heading_and_continuation():
    parse = DocParse("t", [("제1장 총칙", "Heading 1", "1"), ("제1조 유동성 점검 회의를 소집하고 자금 현황을", "", "2"),
                           ("확인한다.", "", "3"), ("(1) 리스크관리팀은 CDS를 모니터링한다.", "", "4"),
                           ("① 외화 한도를 하향 조정한다.", "", "5"), ("가. 감독기관에 보고한다.", "", "6")])
    cl = split_clauses(parse)
    assert [c.text[:3] for c in cl] == ["제1조", "(1)", "① 외", "가. "]
    assert cl[0].text.endswith("자금 현황을 확인한다.") and cl[0].section == "제1장 총칙"


def test_pdf_wrapped_korean_lines_joined_without_space():
    text = "1. 전 자산군이 동반 하락하면 즉시 유동성 점\n검 회의를 소집한다.\n2. 짧은 줄."
    assert _pdf_lines(text)[0].endswith("유동성 점검 회의를 소집한다.")


def test_validation_keeps_only_evidence_backed_owner_and_protection():
    raw = RawClause("제3조 중대 손실이 발생하면 준법감시팀이 감독기관에 즉시 보고한다.")
    bad = ClauseAttrs(index=0, owner_role="재무팀", protected="regulatory", protected_evidence="법령에 따라")
    v, issues = validate_attrs(raw, bad, roles_in_doc=set())
    assert v.owner_role == "준법감시팀"  # 원문에 없는 '재무팀'은 버리고 원문 부서명으로
    assert v.protected == "regulatory" and v.protected_evidence in raw.text  # 인용이 원문에 없으면 규칙 키워드 근거로
    assert any("원문에 없음" in i for i in issues)
    plain = RawClause("제4조 시장 안정 여부를 확인하고 추가 매도를 보류한다.")
    v2, _ = validate_attrs(plain, ClauseAttrs(index=0, protected="insurance", protected_evidence="보험금"), set())
    assert v2.protected == "none"  # 근거 없는 보호 판단은 버린다


def test_uploaded_playbooks_get_separate_index_and_note(monkeypatch, tmp_path):
    from app.agents import orchestrator as orch
    from app.config import ROOT_DIR
    from tests.test_orchestrator import FakeLLM

    r = ingest_document((SAMPLES / "PB-BANK.docx").read_bytes(), "PB-BANK.docx")
    index, note = orch._index([r.playbook], FakeLLM())
    assert set(index.clauses) == {c.clause_id for c in r.playbook.clauses}
    assert "업로드 1개" in note
