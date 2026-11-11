import json
from pathlib import Path

import pytest

from app.ingest.mapper import ColumnMap, rule_mapping, unit_from_header
from app.ingest.pipeline import ingest
from app.ingest.profile import profile_text
from app.ingest.reader import read_csv_bytes
from app.ingest.profile import profile_sheet
from app.ingest.transform import isin_valid, norm_country, to_portfolio

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "ingest" / "samples"
TRUTH = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))


def _by_name(df):
    return {r["name"]: r for r in df.to_dict("records")}


@pytest.mark.parametrize("fname", ["broker_balance.xlsx", "manager_report.xlsx", "dataguide_style.xlsx"])
def test_rule_mapping_reproduces_truth_on_standard_layouts(fname):
    res, _ = ingest(SAMPLES / fname, use_preset=False)
    got = _by_name(res.holdings)
    assert len(got) == TRUTH["n"]
    for t in TRUTH["holdings"]:
        g = got[t["name"]]
        assert g["amount"] == pytest.approx(t["amount"], rel=1e-9)  # 단위 환산 정확
        assert g["country"] == t["country"]
    assert abs(res.holdings["weight"].sum() - 1) < 1e-4
    assert res.chain[-1]["결과"] == "통과"


def test_number_format_scaling_is_display_only():
    # DataGuide 스타일: 저장값은 원, 서식 '#,##0,,'은 표시만 백만 → 환산하면 안 된다
    mult, why = unit_from_header("시가평가액", "#,##0,,")
    assert mult == 1.0 and "표시" in why
    assert unit_from_header("평가액(억 원)", None)[0] == 1e8
    assert unit_from_header("잔액", None, ["※ 금액 단위: 천원"])[0] == 1e3


def test_mixed_identifier_column_split_by_format():
    res, _ = ingest(SAMPLES / "dataguide_style.xlsx", use_preset=False)
    df = res.holdings
    assert df["isin"].notna().sum() + df["local_code"].notna().sum() == TRUTH["n"]
    assert all(isin_valid(x) for x in df["isin"].dropna())


def test_unusual_headers_flagged_without_llm_and_fixed_by_llm_spec():
    res, prof = ingest(SAMPLES / "unusual_headers.xlsx", use_preset=False)
    assert "확인 필요" in res.chain[-1]["결과"]  # 규칙만으로는 금액 열을 못 찾음 → 숨기지 않고 표시
    assert "잔액(KRW, 천)" in profile_text(prof)

    class FakeLLM:  # LLM이 낸 매핑(일부 단위 오류 포함)을 코드가 통계로 바로잡는지
        def generate(self, prompt, purpose, response_schema, system):
            return response_schema(header_row=2, columns=[
                ColumnMap(source="자산명칭(국문)", field="name"), ColumnMap(source="잔액(KRW, 천)", field="amount", multiplier=1),
                ColumnMap(source="편입 비율", field="weight", percent=False), ColumnMap(source="발행국", field="country"),
                ColumnMap(source="분류", field="asset_class"), ColumnMap(source="없는열", field="sector")])

    res, _ = ingest(SAMPLES / "unusual_headers.xlsx", llm=FakeLLM(), use_preset=False)
    got = _by_name(res.holdings)
    notes = " ".join(res.spec.notes)
    assert "없는 열" in notes  # 지어낸 열은 버린다
    assert "÷100 적용" in notes and "표기 채택" in notes  # 통계·단위 표기로 LLM 오류 교정
    for t in TRUTH["holdings"][:20]:
        assert got[t["name"]]["amount"] == pytest.approx(t["amount"], rel=1e-6)
        assert got[t["name"]]["asset_class"] == t["asset_class"]


def test_real_public_file_nps_converts():
    res, _ = ingest(SAMPLES / "nps_domestic_equity_2025.csv", use_preset=False)
    df = res.holdings
    assert len(df) > 1000 and (df["country"] == "KR").all()
    assert df.iloc[0]["name"] == "삼성전자" and df.iloc[0]["amount"] == pytest.approx(551095e8)


def test_csv_preamble_and_quoted_numbers():
    raw = ('Fund X\nFund Holdings as of,"Oct 15, 2026"\n\nTicker,Name,Asset Class,Market Value,Weight (%),Location,Currency\n'
           '"AAA","Alpha Inc","Equity","1,000.50","60.00","United States","USD"\n'
           '"BBB","Beta Plc","Equity","667.00","40.00","United Kingdom","USD"\n').encode()
    p = profile_sheet(read_csv_bytes(raw))
    assert p.header_row == 3 and p.preamble
    spec = rule_mapping(p)
    assert {c.field for c in spec.columns} >= {"ticker", "name", "amount", "weight", "country", "currency"}


def test_country_normalization_and_portfolio_conversion():
    assert norm_country("한국") == "KR" and norm_country("United States") == "US" and norm_country("kr") == "KR"
    res, _ = ingest(SAMPLES / "broker_balance.xlsx", use_preset=False)
    pf = to_portfolio(res.holdings)
    assert abs(sum(n.weight for n in pf.nodes) - 1) < 1e-9 and len(pf.nodes) <= 40
    assert pf.base_currency == "KRW"


# ---------- 입력 오류·경계 사례 ----------


def _xlsx(rows):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_preset_rechecks_unit_and_header_row(monkeypatch, tmp_path):
    from app.ingest import transform

    monkeypatch.setattr(transform, "PRESET_DIR", tmp_path)
    res, prof = ingest(_xlsx([["보유내역"], ["(단위: 억원)"], ["종목명", "국가", "평가금액"], ["A", "KR", 10], ["B", "US", 5]]), "a.xlsx",
                       use_preset=False)
    transform.save_preset(prof, res.spec)
    # 같은 헤더, 다른 헤더 위치·단위 → 저장값(3행·억원)을 그대로 쓰면 0행·100배 오류
    res2, _ = ingest(_xlsx([["(단위: 백만원)"], ["종목명", "국가", "평가금액"], ["A", "KR", 1000], ["B", "US", 500]]), "b.xlsx")
    assert res2.spec.method == "preset" and res2.spec.header_row == 2
    assert res2.holdings["amount"].tolist() == [1000e6, 500e6]
    res3, _ = ingest(_xlsx([["종목명", "국가", "평가금액"], ["A", "KR", 1000]]), "c.xlsx")  # 단위 표기 없음 → 환산 취소
    assert res3.spec.method == "preset" and res3.holdings["amount"].tolist() == [1000.0]


def test_numeric_kr_codes_zero_padded():
    res, _ = ingest(_xlsx([["종목명", "종목코드", "평가금액"], ["삼성전자", 5930, 100], ["SK하이닉스", 660.0, 50], ["LG엔솔", 373220, 50]]),
                    "a.xlsx", use_preset=False)
    assert res.holdings["local_code"].tolist() == ["005930", "000660", "373220"]
    assert (res.holdings["country"] == "KR").all()


def test_unit_words_longest_first_and_whole_tokens():
    assert unit_from_header("평가금액(십억원)", None)[0] == 1e9
    assert unit_from_header("평가금액(만원)", None)[0] == 1e4
    assert unit_from_header("평가금액(천만원)", None)[0] == 1e7
    assert unit_from_header("평가금액(천억원)", None)[0] == 1e11
    assert unit_from_header("잔액(백만 원)", None)[0] == 1e6
    assert unit_from_header("Market Value (USD billion)", None)[0] == 1e9
    assert unit_from_header("MV (USD bn)", None)[0] == 1e9 and unit_from_header("MV (USD mn)", None)[0] == 1e6
    assert unit_from_header("Market value (KRW '000)", None)[0] == 1e3
    assert unit_from_header("Column value", None)[0] == 1.0  # 'Column' 안의 mn은 단위가 아니다


def test_spaced_total_rows_skipped():
    rows = [["종목명", "국가", "평가금액"], ["A", "KR", 100], ["B", "US", 100], ["합 계", "", 200], ["총 합계", None, 200], ["Total ", None, 200]]
    res, _ = ingest(_xlsx(rows), "a.xlsx", use_preset=False)
    assert res.holdings["name"].tolist() == ["A", "B"] and len(res.dropped) == 3
    assert res.holdings["weight"].tolist() == [0.5, 0.5]


def test_to_portfolio_rejects_zero_weight_and_empty():
    res, _ = ingest(_xlsx([["종목명", "국가"], ["A", "KR"], ["B", "US"]]), "a.xlsx", use_preset=False)
    with pytest.raises(ValueError, match="비중 합계가 0"):
        to_portfolio(res.holdings)
    with pytest.raises(ValueError, match="거래상대방"):
        to_portfolio(res.holdings.assign(holding_type="counterparty"))
    with pytest.raises(ValueError, match="보유 종목이 없어"):
        to_portfolio(res.holdings.iloc[0:0])


def test_empty_file_and_bad_header_row_fail_without_crash():
    from app.ingest.mapper import MappingSpec
    from app.ingest.reader import read_file
    from app.ingest.transform import apply_spec

    for data, name in ((b"", "x.csv"), (_xlsx([]), "y.xlsx")):
        res, _ = ingest(data, name, use_preset=False)
        assert res.holdings.empty and res.chain[-1]["결과"] == "실패"
    sh = read_file(_xlsx([["종목명", "평가금액"], ["A", 1]]), "a.xlsx")[0]
    for hr in (0, 99):
        res = apply_spec(sh, profile_sheet(sh), MappingSpec(sheet=sh.name, header_row=hr, columns=[ColumnMap(source="종목명", field="name")]))
        assert res.holdings.empty and res.chain[-1]["결과"] == "실패" and "범위" in res.chain[-1]["원인"]


def test_reader_utf16_csv_and_legacy_xls():
    from app.ingest.reader import read_file

    sh = read_csv_bytes("종목명\t평가금액\n삼성전자\t100\n".encode("utf-16"))
    assert sh.encoding == "utf-16" and sh.rows[1] == ["삼성전자", "100"]
    with pytest.raises(ValueError, match="97-2003"):
        read_file(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 100, "old.xls")


def test_to_number_korean_and_currency_notation():
    from app.ingest.profile import to_number

    assert to_number("△1,000") == -1000 and to_number("▲ 500") == -500
    assert to_number("1,000원") == 1000 and to_number("₩1,000") == 1000 and to_number("$1,000") == 1000
    assert to_number("(1,000)") == -1000 and to_number("원화") is None


def test_country_aliases_checked_before_two_letter_code():
    assert norm_country("UK") == "GB" and norm_country("uk") == "GB"
    assert norm_country("Korea, Republic of") == "KR" and norm_country("US") == "US"
