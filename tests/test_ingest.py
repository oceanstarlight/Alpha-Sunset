import json
from pathlib import Path

import pytest

from app.ingest.mapper import ColumnMap, MappingSpec, check_units, merge, rule_mapping, unit_from_header
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
