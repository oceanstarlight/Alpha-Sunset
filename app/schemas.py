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
    actions_to_check: list[str] = []
    evidence_refs: list[str] = []
    trace_id: str


class Feedback(BaseModel):
    run_id: str
    doc_id: str
    label: Literal["useful", "not_fit"]
    user_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
