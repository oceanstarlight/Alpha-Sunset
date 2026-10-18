"""도메인 스키마 (plans.md 3장)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class EventType(str, Enum):
    liquidity_crisis = "liquidity_crisis"
    credit_event = "credit_event"
    banking_stress = "banking_stress"
    geopolitical = "geopolitical"
    supply_chain = "supply_chain"
    trade_policy = "trade_policy"
    pandemic = "pandemic"
    rate_shock = "rate_shock"
    fx_shock = "fx_shock"
    regulatory = "regulatory"
    other = "other"


class Channel(str, Enum):
    liquidity = "liquidity"
    credit_spread = "credit_spread"
    counterparty = "counterparty"
    fx = "fx"
    commodity = "commodity"
    supply_chain = "supply_chain"
    rates = "rates"
    equity_vol = "equity_vol"
    sanctions_trade = "sanctions_trade"
    operational = "operational"


class Duration(str, Enum):
    shock = "shock"
    weeks = "weeks"
    months = "months"
    structural = "structural"


class Verdict(str, Enum):
    applicable = "applicable"
    partial = "partial"
    not_applicable = "not_applicable"
    uncertain = "uncertain"


class AlertLevel(str, Enum):
    ALERT = "ALERT"
    WATCH = "WATCH"
    NONE = "NONE"


Score = Annotated[float, Field(ge=0.0, le=1.0)]


class Event(BaseModel):
    id: str
    title: str
    date: date
    summary: str
    type: EventType
    channels: list[Channel]
    regions: list[str] = []
    sectors: list[str] = []
    asset_classes: list[str] = []
    entities: list[str] = []
    duration: Duration
    severity: int = Field(ge=1, le=5)
    sources: list[str] = []
    # 백테스트 입력용: 사건일 당일까지 알려진 사실만 담은 요약·기관 (summary에는 사후 사실이 섞여 있음)
    summary_as_of: str | None = None
    entities_as_of: list[str] | None = None

    def as_of_view(self) -> Event:
        """사건일 시점 정보만 남긴 사본. 백테스트 에이전트 입력은 이것을 쓴다."""
        update: dict = {}
        if self.summary_as_of is not None:
            update["summary"] = self.summary_as_of
        if self.entities_as_of is not None:
            update["entities"] = self.entities_as_of
        return self.model_copy(update=update)


class Premises(BaseModel):
    """조항이 작성 당시 전제한 사건 조건."""

    event_types: list[EventType] = []
    channels: list[Channel] = []
    regions: list[str] = []
    asset_classes: list[str] = []
    duration: list[Duration] = []
    conditions: list[str] = []


class Clause(BaseModel):
    clause_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    text: str
    premises: Premises
    actions: list[str] = []
    owner_role: str
    protected: bool = False
    protected_reason: Literal["regulatory", "insurance"] | None = None

    @model_validator(mode="after")
    def _protected_reason(self) -> Clause:
        if self.protected and self.protected_reason is None:
            raise ValueError("protected 조항은 protected_reason이 필요하다")
        if not self.protected and self.protected_reason is not None:
            raise ValueError("protected가 아닌 조항에 protected_reason을 둘 수 없다")
        return self


class Playbook(BaseModel):
    doc_id: str = Field(min_length=1)
    title: str
    version: str
    year: int
    origin_event: str
    synthetic: bool
    source_refs: list[str] = []
    clauses: list[Clause]

    @model_validator(mode="after")
    def _clause_doc_ids(self) -> Playbook:
        wrong = [c.clause_id for c in self.clauses if c.doc_id != self.doc_id]
        if wrong:
            raise ValueError(f"doc_id 불일치 조항: {wrong}")
        return self


class ClauseJudgment(BaseModel):
    clause_id: str = Field(min_length=1)
    verdict: Verdict
    mismatch_reasons: list[str] = []
    evidence_quote: str = ""
    confidence: Score

    @model_validator(mode="after")
    def _evidence_required(self) -> ClauseJudgment:
        # 불변 규칙: 근거 없는 판정은 uncertain만 허용
        if self.verdict != Verdict.uncertain and not self.evidence_quote.strip():
            raise ValueError("uncertain 외 판정은 evidence_quote(근거 인용문)가 필수다")
        return self


class DocFit(BaseModel):
    doc_id: str
    fit_score: Score
    n_applicable: int = Field(ge=0)
    n_partial: int = Field(ge=0)
    n_not: int = Field(ge=0)
    n_uncertain: int = Field(ge=0)
    judgments: list[ClauseJudgment]


class MatchResult(BaseModel):
    event_id: str
    doc_fits: list[DocFit]
    gaps: list[Channel] = []
    low_confidence: bool = False


class ExposurePath(BaseModel):
    nodes: list[str] = Field(min_length=2)  # Institution→Manager/Counterparty→Fund→Holding→Region/Sector
    weight: Score
    relevance: Score
    uncertainty: Score
    risk_score: Score
    why: str = ""


class Briefing(BaseModel):
    run_id: str
    event: Event
    alert_level: AlertLevel
    match: MatchResult
    exposure_top: list[ExposurePath] = []
    exposure_entities: list[ExposurePath] = []  # 사건 기관과 같은 발행자 보유 (순위와 별도)
    exposure_core: list[ExposurePath] = []  # 사건의 구체 지역과 일치하는 경로 (상위 N 밖, 순위와 별도)
    exposure_note: str = ""  # 예: 보유내역 스냅샷 없음
    actions_to_check: list[str] = []
    evidence_refs: list[str] = []
    trace_id: str


class Feedback(BaseModel):
    run_id: str
    doc_id: str
    label: Literal["useful", "not_fit"]
    user_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- P2 코퍼스 스키마 ---


class CalmWindow(BaseModel):
    """오경보 측정용 평상 구간 (사건 없는 분기)."""

    id: str = Field(pattern=r"^calm_")
    start: date
    end: date
    selection_method: str
    stats: dict[str, float] = {}
    sources: list[str] = Field(min_length=1)


class ProxyFund(BaseModel):
    """위탁운용 mandate를 대신하는 공개 펀드. N-PORT series_id는 P1에서 채운다."""

    name: str
    ticker: str
    sponsor: str
    nport_series_id: str | None = None


class PortfolioNode(BaseModel):
    id: str
    name: str
    kind: Literal["direct", "manager", "counterparty"]
    instrument: str  # 예: etf, bond, mmf, fund, swap, repo
    weight: Score  # 총자산 대비 비중 (counterparty는 노출 금액 비중)
    uncertainty: Score
    regions: list[str] = []
    sectors: list[str] = []
    asset_classes: list[str] = []
    proxy_fund: ProxyFund | None = None
    note: str = ""

    @model_validator(mode="after")
    def _kind_rules(self) -> PortfolioNode:
        if self.kind == "manager" and self.proxy_fund is None:
            raise ValueError("manager 노드는 proxy_fund가 필요하다")
        return self


class Portfolio(BaseModel):
    institution: str
    as_of: date
    base_currency: str
    synthetic: bool
    nodes: list[PortfolioNode]

    @model_validator(mode="after")
    def _weights(self) -> Portfolio:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("노드 id 중복")
        total = sum(n.weight for n in self.nodes if n.kind != "counterparty")
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"direct+manager 비중 합이 1이 아니다: {total}")
        return self


class Label(BaseModel):
    """백테스트 정답 (사용자가 직접 설계한 합성 라벨)."""

    event_id: str
    reaction_date: date
    expected_docs: list[str]
    expected_inapplicable_clauses: list[str] = []
    expected_gap_channels: list[Channel] = []
    expected_exposure_paths: list[str] = []  # 포트폴리오 노드 id
    synthetic: bool = True
    notes: str = ""
