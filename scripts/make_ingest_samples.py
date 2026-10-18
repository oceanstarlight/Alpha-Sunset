"""입력 변환 검증용 합성 파일 3종 + 정답 (data/ingest/samples/).

같은 보유내역(정답)을 서로 다른 실무 양식으로 써서, 변환 결과를 정답과 비교할 수 있게 한다.
- broker_balance.xlsx : 증권사 잔고 양식 (제목·병합 셀, 'A' 붙은 종목코드, 원 단위, % 비중, 한글 국가명, 합계 행)
- manager_report.xlsx : 운용사 보고 양식 (요약 시트 + 보유 시트, ISIN, 백만원 단위, 0~1 비율에 % 서식, 직접/위탁 구분)
- dataguide_style.xlsx: 데이터 단말 내보내기 양식 (메타 5행, 'Symbol', 저장값은 원인데 서식 '#,##0,,'으로 백만 표시)
- unusual_headers.xlsx: 규칙 사전에 없는 열 이름 (잔액·발행국·분류·관리주체, 단위는 메모 행 '천원')
사용: python scripts/make_ingest_samples.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402

from app.config import ROOT_DIR  # noqa: E402

OUT = ROOT_DIR / "data" / "ingest" / "samples"
KO = {"KR": "한국", "US": "미국", "CN": "중국", "JP": "일본", "DE": "독일", "GB": "영국", "VN": "베트남"}
ASSET_KO = {"equity": "주식", "govt_bond": "국채", "corporate_bond": "회사채", "money_market": "현금성자산", "real_estate": "부동산"}
SECTORS = ["Information Technology", "Financials", "Energy", "Industrials", "Consumer Discretionary", "Health Care"]


def isin_with_check(body11: str) -> str:
    digits = "".join(str(int(ch, 36)) for ch in body11)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return body11 + str((10 - total % 10) % 10)


def truth(n: int = 240, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        country = rng.choices(list(KO), weights=[50, 25, 8, 6, 4, 4, 3])[0]
        asset = rng.choices(list(ASSET_KO), weights=[60, 15, 15, 6, 4])[0]
        code = f"{rng.randint(1, 999999):06d}"
        body = (country + ("7" if country == "KR" else "0") + code + f"{i:03d}")[:11]
        amount = round(rng.lognormvariate(22, 1.2), -3)  # 원 단위 (천원 단위 반올림)
        rows.append({"name": f"합성종목{i:03d}", "isin": isin_with_check(body), "local_code": code if country == "KR" else None,
                     "amount": amount, "country": country, "asset_class": asset, "sector": rng.choice(SECTORS),
                     "holding_type": rng.choices(["direct", "manager"], weights=[70, 30])[0]})
    total = sum(r["amount"] for r in rows)
    for r in rows:
        r["weight"] = r["amount"] / total
    return rows


def broker(rows: list[dict], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "잔고현황"
    ws["A1"] = "주식·채권 잔고 현황"
    ws.merge_cells("A1:G1")
    ws["A2"] = "기준일: 2026-10-16   계좌: ****-1234"
    ws.merge_cells("A2:G2")
    ws.append([])
    ws.append(["종목코드", "종목명", "자산구분", "국가", "평가금액(원)", "비중(%)", "업종"])
    for r in rows:
        code = f"A{r['local_code']}" if r["local_code"] else r["isin"][2:8]
        ws.append([code, r["name"], ASSET_KO[r["asset_class"]], KO[r["country"]], r["amount"], round(r["weight"] * 100, 4), r["sector"]])
        ws.cell(ws.max_row, 5).number_format = "#,##0"
    ws.append(["합계", None, None, None, sum(r["amount"] for r in rows), 100.0, None])
    wb.save(path)


def manager(rows: list[dict], path: Path) -> None:
    wb = Workbook()
    s = wb.active
    s.title = "요약"
    s.append(["구분", "금액(백만원)"])
    s.append(["직접", round(sum(r["amount"] for r in rows if r["holding_type"] == "direct") / 1e6, 1)])
    s.append(["위탁", round(sum(r["amount"] for r in rows if r["holding_type"] == "manager") / 1e6, 1)])
    ws = wb.create_sheet("보유내역")
    ws.append(["2026년 3분기 위탁운용 보고"])
    ws.append(["ISIN", "Security Name", "운용구분", "Country", "Market Value (KRW mn)", "Weight", "GICS Sector"])
    for r in rows:
        ws.append([r["isin"], r["name"], "직접" if r["holding_type"] == "direct" else "위탁", r["country"],
                   round(r["amount"] / 1e6, 3), r["weight"], r["sector"]])
        ws.cell(ws.max_row, 5).number_format = "#,##0.0"
        ws.cell(ws.max_row, 6).number_format = "0.00%"
    wb.save(path)


def dataguide(rows: list[dict], path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for line in (["Refresh", "Last Updated: 2026-10-16 18:00"], ["Frequency", "DAILY"], ["Item", "시가평가액"],
                 ["Data Source", "Synthetic export (DataGuide 스타일)"], []):
        ws.append(line)
    ws.append(["Symbol", "Name", "시가평가액", "Asset Type", "Nation"])
    for r in rows:
        sym = f"A{r['local_code']}" if r["local_code"] else r["isin"]
        ws.append([sym, r["name"], r["amount"], {"equity": "Equity", "govt_bond": "Government Bond", "corporate_bond": "Corporate Bond",
                                                  "money_market": "Cash", "real_estate": "REIT"}[r["asset_class"]], r["country"]])
        ws.cell(ws.max_row, 3).number_format = "#,##0,,"  # 표시만 백만 단위, 저장값은 원
    wb.save(path)


def unusual(rows: list[dict], path: Path) -> None:
    """규칙 사전에 없는 열 이름 (LLM 해석이 필요한 경우)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "포지션"
    ws.append(["※ 금액 단위: 천원"])
    ws.append(["자산명칭(국문)", "잔액(KRW, 천)", "편입 비율", "발행국", "분류", "관리주체"])
    for r in rows:
        ws.append([r["name"], round(r["amount"] / 1e3, 3), round(r["weight"] * 100, 4), KO[r["country"]],
                   ASSET_KO[r["asset_class"]], "자체" if r["holding_type"] == "direct" else "외부위탁"])
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = truth()
    broker(rows, OUT / "broker_balance.xlsx")
    manager(rows, OUT / "manager_report.xlsx")
    dataguide(rows, OUT / "dataguide_style.xlsx")
    unusual(rows, OUT / "unusual_headers.xlsx")
    (OUT / "truth.json").write_text(json.dumps({"synthetic": True, "n": len(rows), "currency": "KRW",
                                                "total_amount": sum(r["amount"] for r in rows), "holdings": rows},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)}행 × 4 양식 → {OUT}")


if __name__ == "__main__":
    main()
