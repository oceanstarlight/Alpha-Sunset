"""입력 변환 파이프라인: 읽기 → 구조 요약 → 매핑(저장 양식 > LLM+규칙 > 규칙) → 변환·검증."""

from __future__ import annotations

from pathlib import Path

from app.ingest.mapper import MappingSpec, llm_mapping, merge, rule_mapping
from app.ingest.profile import SheetProfile, profile_sheet
from app.ingest.reader import Sheet, read_file
from app.ingest.transform import IngestResult, apply_spec, load_preset


def pick_sheet(sheets: list[Sheet]) -> tuple[Sheet, SheetProfile]:
    """데이터가 가장 많은 시트."""
    profiled = [(s, profile_sheet(s)) for s in sheets]
    return max(profiled, key=lambda sp: sum(c.n_values for c in sp[1].columns))


def propose(sheet: Sheet, profile: SheetProfile, llm=None, use_preset: bool = True) -> MappingSpec:
    if use_preset and (preset := load_preset(profile)):
        return preset
    rule = rule_mapping(profile)
    return merge(rule, llm_mapping(profile, llm) if llm is not None else None, profile)


def ingest(src: Path | bytes, filename: str | None = None, llm=None, spec: MappingSpec | None = None,
           use_preset: bool = True) -> tuple[IngestResult, SheetProfile]:
    sheets = read_file(src, filename)
    sheet, profile = pick_sheet(sheets)
    if spec is not None:
        sheet = next(s for s in sheets if s.name == spec.sheet) if any(s.name == spec.sheet for s in sheets) else sheet
        profile = profile_sheet(sheet)
    spec = spec or propose(sheet, profile, llm, use_preset)
    return apply_spec(sheet, profile, spec), profile
