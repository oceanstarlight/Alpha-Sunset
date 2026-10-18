"""표 구조 요약 — 헤더 행 추정, 열 통계, 숫자 서식을 글로 바꿔 LLM이 구조를 해석하게 한다.

전체 숫자는 넘기지 않는다. 샘플 행의 숫자는 기본으로 유효숫자 2자리로 흐린다 (mask=True).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.ingest.reader import Sheet

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
KR_CODE_RE = re.compile(r"^A?\d{6}$")
TOTAL_WORDS = ("합계", "소계", "총계", "total", "subtotal", "계")


def to_number(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and math.isnan(v) else float(v)
    s = str(v).strip().replace(",", "").replace("%", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _is_text(v) -> bool:
    return isinstance(v, str) and v.strip() != "" and to_number(v) is None


def guess_header_row(rows: list[list], scan: int = 40) -> int:
    """0-based. 문자열 셀이 가장 많고, 아래 행들에 숫자가 이어지는 행."""
    best, best_score = 0, -1.0
    for i, row in enumerate(rows[:scan]):
        texts = sum(_is_text(v) for v in row)
        if texts < 2:
            continue
        below = rows[i + 1: i + 6]
        nums = sum(sum(to_number(v) is not None for v in r) for r in below) / max(len(below), 1)
        score = texts + nums * 0.8
        if score > best_score:
            best, best_score = i, score
    return best


@dataclass
class ColumnStat:
    index: int
    header: str
    n_values: int
    numeric_ratio: float
    min: float | None = None
    max: float | None = None
    sum: float | None = None
    samples: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)  # isin / kr_code / country_like
    number_format: str | None = None


@dataclass
class SheetProfile:
    sheet: str
    n_rows: int
    n_cols: int
    header_row: int  # 0-based
    headers: list[str]
    columns: list[ColumnStat]
    preamble: list[str]
    total_rows: list[int]  # 0-based, 합계·소계로 보이는 행
    merged: list[str]

    @property
    def signature(self) -> str:
        """같은 양식 판별용 (헤더 이름 정규화)."""
        return "|".join(re.sub(r"\s+", "", h).lower() for h in self.headers)


def _blur(v: float) -> str:
    if v == 0:
        return "0"
    return f"{v:.2g}"


def profile_sheet(sheet: Sheet, mask: bool = True, n_samples: int = 5) -> SheetProfile:
    rows = [r for r in sheet.rows]
    h = guess_header_row(rows)
    headers = [str(v).strip() if v is not None else "" for v in rows[h]] if rows else []
    data = rows[h + 1:]
    total_rows = [h + 1 + i for i, r in enumerate(data)
                  if any(isinstance(v, str) and v.strip().lower() in TOTAL_WORDS for v in r[:3])]
    cols = []
    for j, name in enumerate(headers):
        vals = [r[j] for r in data if j < len(r) and r[j] not in (None, "")]
        nums = [x for x in (to_number(v) for v in vals) if x is not None]
        texts = [str(v).strip() for v in vals]
        stat = ColumnStat(index=j, header=name, n_values=len(vals), numeric_ratio=round(len(nums) / max(len(vals), 1), 2),
                          number_format=sheet.number_formats.get(j))
        if nums:
            stat.min, stat.max, stat.sum = min(nums), max(nums), round(sum(nums), 4)
        sample_vals = texts[:n_samples]
        stat.samples = [_blur(to_number(s)) if mask and to_number(s) is not None and abs(to_number(s)) >= 1000 else s[:30]
                        for s in sample_vals]
        if texts and sum(bool(ISIN_RE.match(t)) for t in texts[:50]) >= min(3, len(texts[:50])):
            stat.patterns.append("isin")
        head = texts[:50]
        # 6자리 숫자는 금액과 헷갈리므로 앞자리 0 또는 'A' 접두가 하나라도 있어야 종목코드로 본다
        if head and sum(bool(KR_CODE_RE.match(t)) for t in head) >= min(3, len(head)) and any(t[0] in "0A" for t in head):
            stat.patterns.append("kr_code")
        cols.append(stat)
    preamble = [" | ".join(str(v) for v in r if v not in (None, ""))[:120] for r in rows[:h] if any(v not in (None, "") for v in r)]
    return SheetProfile(sheet=sheet.name, n_rows=len(rows), n_cols=len(headers), header_row=h, headers=headers,
                        columns=cols, preamble=preamble, total_rows=total_rows, merged=sheet.merged[:10])


def profile_text(p: SheetProfile) -> str:
    """LLM 입력용 요약 글."""
    lines = [f"시트 '{p.sheet}' (행 {p.n_rows} · 열 {p.n_cols})"]
    if p.preamble:
        lines.append(f"- 헤더 위 {len(p.preamble)}행(제목·메타): " + " / ".join(p.preamble[:8]))
    if p.merged:
        lines.append(f"- 병합 셀: {', '.join(p.merged)}")
    lines.append(f"- 추정 헤더: {p.header_row + 1}행")
    if p.total_rows:
        lines.append(f"- 합계·소계로 보이는 행: {', '.join(str(r + 1) for r in p.total_rows[:5])}")
    lines.append("- 열:")
    for c in p.columns:
        if not c.header and not c.n_values:
            continue
        desc = f"  [{c.index}] '{c.header}' 값 {c.n_values}개, 숫자 비율 {c.numeric_ratio}"
        if c.min is not None:
            desc += f", 범위 {_blur(c.min)}~{_blur(c.max)}, 합계 {_blur(c.sum)}"
        if c.number_format:
            desc += f", 서식 '{c.number_format}'"
        if c.patterns:
            desc += f", 패턴 {c.patterns}"
        desc += f", 샘플 {c.samples}"
        lines.append(desc)
    return "\n".join(lines)
