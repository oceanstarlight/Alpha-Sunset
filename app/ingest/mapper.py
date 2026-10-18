"""열 매핑 규칙 — 규칙 기반(별칭·패턴·단위 표기) + LLM(표 요약 글만 보고 규칙 반환).

LLM이 없는 원본 열 이름을 지어내면 그 항목은 버리고 규칙 결과를 쓴다 (근거 검증과 같은 원칙).
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

from app.ingest.profile import SheetProfile, profile_text
from app.ingest.schema import FIELDS

Field = Literal["name", "isin", "ticker", "local_code", "amount", "currency", "weight", "asset_class", "country",
                "sector", "holding_type", "manager"]

UNIT_WORDS = [("조원", 1e12), ("억원", 1e8), ("억 원", 1e8), ("백만원", 1e6), ("백만 원", 1e6), ("천원", 1e3),
              ("천 원", 1e3), ("mn", 1e6), ("million", 1e6), ("thousand", 1e3), ("bn", 1e9)]


TEXT_FIELDS = {"name", "asset_class", "country", "sector", "holding_type", "manager", "currency"}


class ColumnMap(BaseModel):
    source: str  # 원본 헤더 이름
    field: Field
    multiplier: float = 1.0  # amount 단위 환산 (예: 억원 → 1e8)
    percent: bool = False  # weight가 % 값이면 True (÷100)
    reason: str = ""


class MappingSpec(BaseModel):
    sheet: str
    header_row: int  # 1-based
    skip_if_contains: list[str] = ["합계", "소계", "총계", "Total"]
    columns: list[ColumnMap]
    defaults: dict[str, str] = {}  # 열이 없을 때 고정값 (예: currency=KRW, holding_type=direct)
    default_reasons: dict[str, str] = {}
    method: str = "rule"  # rule | llm | preset
    notes: list[str] = []


def _norm(s: str) -> str:
    return re.sub(r"[\s_()\[\]%·./-]+", "", s).lower()


def _unit_word(text: str) -> tuple[float, str] | None:
    t = text.replace(" ", "").lower()
    for word, mult in UNIT_WORDS:
        if word.replace(" ", "") in t:
            return mult, word
    return None


def unit_from_header(header: str, number_format: str | None, preamble: list[str] | None = None) -> tuple[float, str]:
    if hit := _unit_word(header):
        return hit[0], f"헤더 단위 표기 '{hit[1]}'"
    for line in preamble or []:
        if "단위" in line or "unit" in line.lower():
            if hit := _unit_word(line):
                return hit[0], f"헤더 위 메타 '{line[:30]}'의 단위 표기 '{hit[1]}'"
    if number_format and re.search(r"0(,+)(?:[;\"_]|$)", number_format):
        # 엑셀 서식의 끝 쉼표는 '표시'만 천·백만 단위로 줄이고 저장값은 그대로다 → 환산하지 않는다
        return 1.0, f"숫자 서식 '{number_format}'은 표시 단위만 바꾸고 저장값은 원 단위 → 환산 없음"
    return 1.0, "단위 표기 없음 → 통화 기본 단위로 간주"


def _candidates(p: SheetProfile) -> list[tuple[float, int, str, str]]:
    """(점수, 열 index, 필드, 근거). 값 패턴 > 열 이름 완전 일치 > 긴 별칭 포함."""
    out = []
    for c in p.columns:
        if not c.header:
            continue
        hn = _norm(c.header)
        if "isin" in c.patterns and "kr_code" in c.patterns:
            out.append((100.0, c.index, "isin", "값이 ISIN과 국내 6자리 코드가 섞인 식별자 열 → 값마다 형식으로 나눠 저장"))
        elif "isin" in c.patterns:
            out.append((100.0, c.index, "isin", "값이 ISIN 형식(국가 2자+9자+검증 1자리)"))
        elif "kr_code" in c.patterns:
            out.append((90.0, c.index, "local_code", "값이 국내 6자리 종목코드 형식"))
        for f, (_, aliases) in FIELDS.items():
            for a in aliases:
                an = _norm(a)
                if not an or an not in hn:
                    continue
                score = (50.0 if an == hn else 0.0) + len(an) - 0.01 * (len(hn) - len(an))
                if f in ("amount", "weight") and c.numeric_ratio < 0.8:
                    continue  # 숫자 열이 아니면 금액·비중이 될 수 없다
                if f in TEXT_FIELDS and c.numeric_ratio >= 0.5:
                    continue  # 숫자 열은 이름·분류가 될 수 없다 (예: '자산군 내 비중')
                out.append((score, c.index, f, f"열 이름 '{c.header}' ↔ {f} 별칭 '{a}'" + (" (완전 일치)" if an == hn else "")))
    return sorted(out, reverse=True)


def rule_mapping(p: SheetProfile) -> MappingSpec:
    cols: list[ColumnMap] = []
    used_f, used_c = set(), set()
    by_index = {c.index: c for c in p.columns}
    for _, idx, field, why in _candidates(p):
        if field in used_f or idx in used_c:
            continue
        c = by_index[idx]
        cm = ColumnMap(source=c.header, field=field, reason=why)
        if field == "amount":
            cm.multiplier, unit_why = unit_from_header(c.header, c.number_format, p.preamble)
            cm.reason += f"; {unit_why}"
        if field == "weight":
            if "%" in c.header or "퍼센트" in c.header or (c.sum is not None and 50 <= c.sum <= 150) or (c.max or 0) > 1.5:
                cm.percent = True
                cm.reason += f"; 합계 {c.sum:.4g}·최대 {c.max:.4g} → % 단위(÷100)" if c.sum is not None else "; % 표기"
            else:
                cm.reason += "; 값이 0~1 → 비율 그대로"
        used_f.add(field)
        used_c.add(idx)
        cols.append(cm)
    cols.sort(key=lambda m: list(FIELDS).index(m.field))
    used = used_f
    defaults, reasons, notes = {}, {}, []
    if "currency" not in used:
        heads = " ".join(c.header for c in p.columns).lower() + " " + " ".join(p.preamble).lower()
        if "krw" in heads or "원" in heads or any("kr_code" in c.patterns for c in p.columns):
            defaults["currency"], reasons["currency"] = "KRW", "통화 열 없음 → 헤더의 'KRW'·'원' 표기 또는 국내 6자리 종목코드로 KRW"
        elif "usd" in heads or "$" in heads:
            defaults["currency"], reasons["currency"] = "USD", "통화 열 없음 → 헤더의 'USD'·'$' 표기로 USD"
        else:
            notes.append("통화를 판단할 근거 없음 → 사람 확인 필요")
    if "country" not in used and not any(f in used for f in ("isin", "local_code")):
        ctx = (p.sheet + " " + " ".join(p.preamble)).lower()
        if any(w in ctx for w in ("국내", "domestic", "kospi", "코스피", "코스닥")):
            defaults["country"], reasons["country"] = "KR", f"국가 열 없음 → 파일·시트 이름/메타의 국내 표기 ('{p.sheet[:30]}')"
        else:
            notes.append("국가 열·식별자 없음 → 국가 미상 (노출 분석에서 GLOBAL), 사람이 기본값 지정 필요")
    if "holding_type" not in used:
        defaults["holding_type"], reasons["holding_type"] = "direct", "보유 형태 열 없음 → 직접 보유로 간주"
    return MappingSpec(sheet=p.sheet, header_row=p.header_row + 1, columns=cols, defaults=defaults,
                       default_reasons=reasons, method="rule", notes=notes)


class DefaultValue(BaseModel):
    field: Field
    value: str
    reason: str = ""


class LlmSpec(BaseModel):
    """Gemini 구조화 출력용 (dict 필드 미지원 → 목록으로)."""
    header_row: int
    skip_if_contains: list[str] = []
    columns: list[ColumnMap]
    defaults: list[DefaultValue] = []


LLM_SYSTEM = """너는 금융기관 보유내역 표의 구조를 해석한다. 입력은 표 요약 글(헤더·열 통계·서식·샘플)뿐이다.
공통 스키마 필드에 원본 열을 연결하는 규칙만 JSON으로 돌려준다. 숫자를 계산하거나 지어내지 않는다.
- source는 요약에 나온 열 이름을 글자 그대로 쓴다. 없는 열은 쓰지 않는다.
- amount의 multiplier는 헤더나 헤더 위 메타의 단위 표기(억원=1e8, 백만원=1e6, 천원=1e3)로 정한다. 엑셀 숫자 서식의 끝 쉼표는 표시만 줄일 뿐 저장값은 그대로이므로 환산하지 않는다(1).
- weight가 % 값(합계가 약 100)이면 percent=true.
- header_row는 1부터 센 헤더 행 번호다.
- 열이 없는 필드 중 표 전체에 하나의 값이 명백한 것(통화 등)만 defaults에 field·value·reason으로 쓴다. 근거가 없으면 비운다.
- 각 매핑의 reason에 근거(열 이름·단위·값 범위·패턴)를 한 문장으로 쓴다.
- 합계·소계 행을 거를 단어를 skip_if_contains에 넣는다.
필드 목록:
""" + "\n".join(f"- {k}: {v[0]}" for k, v in FIELDS.items())


def llm_mapping(p: SheetProfile, llm) -> MappingSpec | None:
    try:
        raw = llm.generate(profile_text(p), purpose="ingest_mapping", response_schema=LlmSpec, system=LLM_SYSTEM)
        spec = MappingSpec(sheet=p.sheet, header_row=raw.header_row, columns=raw.columns,
                           skip_if_contains=raw.skip_if_contains or ["합계", "소계", "총계", "Total"],
                           defaults={d.field: d.value for d in raw.defaults},
                           default_reasons={d.field: d.reason for d in raw.defaults})
    except Exception as e:  # 키 없음·한도 초과 등 → 규칙 결과 사용
        return MappingSpec(sheet=p.sheet, header_row=p.header_row + 1, columns=[], method="llm",
                           notes=[f"LLM 매핑 실패: {type(e).__name__}"])
    headers = set(p.headers)
    kept = [c for c in spec.columns if c.source in headers]
    dropped = [c.source for c in spec.columns if c.source not in headers]
    spec.columns = kept
    spec.sheet, spec.method = p.sheet, "llm"
    if dropped:
        spec.notes.append(f"LLM이 없는 열을 지정해 제외: {dropped}")
    return spec


def check_units(spec: MappingSpec, p: SheetProfile) -> MappingSpec:
    """LLM의 단위 판단을 데이터 통계로 검증한다 (코드 검증 우선). 근거 없는 환산은 버린다."""
    by_header = {c.header: c for c in p.columns}
    for cm in spec.columns:
        c = by_header.get(cm.source)
        if c is None:
            continue
        if cm.field == "weight" and c.sum is not None:
            if cm.percent and 0.5 <= c.sum <= 1.5 and (c.max or 0) <= 1.0:
                cm.percent = False
                spec.notes.append(f"weight '{cm.source}': 값 합계 {c.sum:.3g}(0~1 비율)인데 % 판정 → 코드가 ÷100 취소"
                                  + (f" (서식 '{c.number_format}'은 표시만 %)" if c.number_format and "%" in c.number_format else ""))
            elif not cm.percent and 50 <= c.sum <= 150:
                cm.percent = True
                spec.notes.append(f"weight '{cm.source}': 값 합계 {c.sum:.3g}(% 값)인데 비율 판정 → 코드가 ÷100 적용")
        if cm.field == "amount":
            evidence_mult, why = unit_from_header(c.header, c.number_format, p.preamble)
            if abs(cm.multiplier - evidence_mult) > 1e-9 and evidence_mult != 1.0:
                spec.notes.append(f"amount '{cm.source}': LLM ×{cm.multiplier:g} vs 단위 표기 ×{evidence_mult:g} ({why}) → 표기 채택")
                cm.multiplier = evidence_mult
            elif cm.multiplier != 1.0 and evidence_mult == 1.0 and not cm.reason:
                spec.notes.append(f"amount '{cm.source}': 근거 없는 ×{cm.multiplier:g} 환산 → 취소")
                cm.multiplier = 1.0
    return spec


def merge(rule: MappingSpec, llm: MappingSpec | None, p: SheetProfile | None = None) -> MappingSpec:
    """LLM 우선, LLM이 비운 필드는 규칙으로 채운다. 단위는 데이터 통계로 다시 검증한다. 둘이 다르면 기록한다."""
    if llm is None or not llm.columns:
        if llm is not None:
            rule.notes += llm.notes
        return rule
    out = llm.model_copy(deep=True)
    have = {c.field for c in out.columns}
    taken = {c.source for c in out.columns}
    for c in rule.columns:
        mine = next((x for x in out.columns if x.field == c.field), None)
        if mine is None and c.source in taken:
            out.notes.append(f"규칙의 {c.field}←'{c.source}'는 LLM이 같은 열을 다른 필드로 써서 제외")
        elif mine is None:
            out.columns.append(c.model_copy(update={"reason": c.reason + " (규칙 보완)"}))
        elif mine.source != c.source or abs(mine.multiplier - c.multiplier) > 1e-9 or mine.percent != c.percent:
            out.notes.append(f"{c.field}: LLM '{mine.source}'×{mine.multiplier:g}{'%' if mine.percent else ''} vs 규칙 "
                             f"'{c.source}'×{c.multiplier:g}{'%' if c.percent else ''} → LLM 채택, 사람 확인 필요")
    for k, v in rule.defaults.items():
        if k not in have and k not in out.defaults:
            out.defaults[k], out.default_reasons[k] = v, rule.default_reasons.get(k, "")
    out.method = "llm+rule"
    return check_units(out, p) if p is not None else out


def spec_json(spec: MappingSpec) -> str:
    return json.dumps(spec.model_dump(), ensure_ascii=False, indent=2)
