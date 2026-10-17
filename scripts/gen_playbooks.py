"""합성 플레이북 검증·정리 스크립트.

조항 초안은 source_notes 기반으로 작성(현재 Claude 초안)하고 사람이 검수한다.
이 스크립트는 data/playbooks/*.json을 스키마 검증하고 규칙 위반을 보고하며,
--write를 주면 검증된 내용으로 파일을 정규화해 다시 저장한다.

사용: python -m scripts.gen_playbooks [--write]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from app.config import ROOT_DIR
from app.corpus import DATA_DIR, load_playbooks


def check() -> list[str]:
    playbooks = load_playbooks()
    errors = []
    clause_ids = Counter(c.clause_id for p in playbooks for c in p.clauses)
    errors += [f"중복 clause_id: {cid}" for cid, n in clause_ids.items() if n > 1]
    for p in playbooks:
        if not p.synthetic:
            errors.append(f"{p.doc_id}: synthetic=true 필수")
        for ref in p.source_refs:
            if ref.startswith("data/") and not (ROOT_DIR / ref).exists():
                errors.append(f"{p.doc_id}: source_refs 파일 없음 {ref}")
    if not any(c.protected for p in playbooks for c in p.clauses):
        errors.append("protected 조항이 하나도 없다")
    return errors


def summary() -> str:
    playbooks = load_playbooks()
    n_clauses = sum(len(p.clauses) for p in playbooks)
    n_protected = sum(c.protected for p in playbooks for c in p.clauses)
    lines = [f"문서 {len(playbooks)}개, 조항 {n_clauses}개 (protected {n_protected}개)"]
    for p in playbooks:
        lines.append(f"  {p.doc_id:10s} v{p.version:4s} {p.year} origin={p.origin_event:15s} 조항 {len(p.clauses)}  {p.title}")
    return "\n".join(lines)


def write() -> None:
    for p in load_playbooks():
        path = DATA_DIR / "playbooks" / f"{p.doc_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p.model_dump(mode="json"), f, ensure_ascii=False, indent=2)
            f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="검증 통과 시 정규화해 저장")
    args = parser.parse_args()
    errors = check()
    print(summary())
    if errors:
        print("\n".join(["오류:"] + errors))
        return 1
    if args.write:
        write()
        print("정규화 저장 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
