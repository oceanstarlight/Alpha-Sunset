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
    from tests.test_orchestrator import FakeLLM

    r = ingest_document((SAMPLES / "PB-BANK.docx").read_bytes(), "PB-BANK.docx")
    index, note = orch._index([r.playbook], FakeLLM())
    assert set(index.clauses) == {c.clause_id for c in r.playbook.clauses}
    assert "업로드 1개" in note


def test_korean_filenames_get_distinct_doc_and_clause_ids():
    a = ingest_document("제1조 유동성 위기 시 자금팀은 즉시 보고한다.\n".encode(), "위기대응.txt")
    b = ingest_document("제1조 신용 경색 시 리스크관리팀은 한도를 점검한다.\n".encode(), "유동성계획.txt")
    assert a.playbook.doc_id.startswith("UP-DOC-") and a.playbook.doc_id != b.playbook.doc_id
    assert {c.clause_id for c in a.playbook.clauses}.isdisjoint(c.clause_id for c in b.playbook.clauses)
    assert ingest_document((SAMPLES / "PB-BANK.docx").read_bytes(), "PB-BANK.docx").playbook.doc_id == "UP-PB-BANK"  # 영문 이름은 그대로


def test_unreadable_documents_raise_readable_value_error():
    import io
    import zipfile

    import pytest
    from pypdf import PdfWriter

    def pdf(**enc):
        w = PdfWriter()
        w.add_blank_page(100, 100)
        if enc:
            w.encrypt(**enc)
        b = io.BytesIO()
        w.write(b)
        return b.getvalue()

    def zip_with(name):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr(name, "<x/>")
        return b.getvalue()

    cases = [(b"%PDF-1.4 garbage", "a.pdf", "PDF를 읽지 못했다"), (pdf(user_password="secret"), "enc.pdf", "암호"),
             (b"PK\x03\x04junk", "b.docx", "워드"), (zip_with("xl/workbook.xml"), "c.xlsx", "워드"),
             (zip_with("word/document.xml"), "d.docx", "워드 문서를 읽지 못했다"),
             (bytes(range(256)) * 4, "e.txt", "인코딩"), (b"\x00\x01\x02\x03ab" * 50, "f.txt", "텍스트 문서가 아니다")]
    for data, name, msg in cases:
        with pytest.raises(ValueError, match=msg):
            ingest_document(data, name)
    # 권한 암호만 걸린 PDF는 빈 암호로 열린다 (글자 없음 → OCR 안내)
    r = ingest_document(pdf(user_password="", owner_password="owner"), "perm.pdf")
    assert "OCR" in r.chain[0]["결과"]


def test_cp949_text_document_decoded():
    r = ingest_document("제1조 유동성 위기 시 자금팀은 즉시 점검한다.\n".encode("cp949"), "plan.txt")
    assert r.playbook.clauses[0].text.startswith("제1조 유동성 위기")


def test_protect_keywords_are_specific():
    from app.ingest.documents import rule_attrs

    for s in ("제3조 대응 방법은 다음과 같다.", "제4조 법인 카드 한도를 점검한다.", "제5조 보고서를 작성한다.", "제6조 확인 가능한 자금을 쓴다."):
        assert rule_attrs(RawClause(s)).protected == "none", s
    assert rule_attrs(RawClause("제7조 자본시장법에 따라 공시한다.")).protected == "regulatory"
    assert rule_attrs(RawClause("제8조 감독 규정 준수 여부를 확인한다.")).protected == "regulatory"
    assert rule_attrs(RawClause("제9조 예금보험 한도를 확인한다.")).protected == "insurance"
