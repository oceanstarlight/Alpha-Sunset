"""공통 보유내역 스키마 — 공개 표준에 맞춘 필드 (SEC N-PORT 보유 항목, ISO 6166 ISIN, ISO 3166 국가, ISO 4217 통화)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AssetClass = Literal["equity", "govt_bond", "corporate_bond", "money_market", "derivatives", "real_estate",
                     "commodity", "fund", "other"]
HoldingType = Literal["direct", "manager", "counterparty"]

# 필드 → (설명, 별칭). 별칭은 규칙 기반 매핑과 LLM 프롬프트에 함께 쓴다.
FIELDS: dict[str, tuple[str, list[str]]] = {
    "name": ("종목명·발행자명 (N-PORT name)", ["종목명", "종목", "자산명", "명칭", "name", "security", "issuer", "description", "한글종목명"]),
    "isin": ("ISIN (ISO 6166, 12자리)", ["isin", "isin코드", "표준코드", "국제증권식별번호"]),
    "ticker": ("티커·단말 심볼", ["ticker", "티커", "symbol", "심볼"]),
    "local_code": ("국내 단축코드 (6자리)", ["종목코드", "단축코드", "코드", "code", "stock code"]),
    "amount": ("평가금액 (통화 단위로 환산)", ["평가금액", "평가액", "시가평가액", "market value", "marketvalue", "금액", "잔고금액", "value", "notional"]),
    "currency": ("통화 (ISO 4217)", ["통화", "currency", "ccy"]),
    "weight": ("비중 (0~1)", ["비중", "weight", "비율", "%", "편입비"]),
    "asset_class": ("자산군", ["자산구분", "자산군", "자산유형", "asset class", "assetclass", "type", "상품구분"]),
    "country": ("국가 (ISO 3166 alpha-2)", ["국가", "국적", "country", "nation", "location", "소재지", "투자국가", "국가코드"]),
    "sector": ("섹터·업종", ["섹터", "업종", "산업", "sector", "industry", "gics"]),
    "holding_type": ("보유 형태 (direct·manager·counterparty)", ["운용형태", "보유형태", "운용구분", "직접/위탁"]),
    "manager": ("위탁운용사·거래상대방명", ["운용사", "위탁운용사", "manager", "거래상대방", "counterparty"]),
}


class Holding(BaseModel):
    name: str
    isin: str | None = None
    ticker: str | None = None
    local_code: str | None = None
    amount: float | None = None
    currency: str | None = None
    weight: float | None = Field(default=None, ge=-1, le=1)
    asset_class: AssetClass = "other"
    country: str | None = None
    sector: str | None = None
    holding_type: HoldingType = "direct"
    manager: str | None = None
    source_row: int  # 원본 파일 행 번호 (추적용)
