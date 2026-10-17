"""data/ 코퍼스 전체 검증 (플레이북·사건·calm·포트폴리오·라벨).

사용: python -m scripts.validate_data
"""

from __future__ import annotations

import sys

from app.corpus import (
    check_label_refs,
    load_calm_windows,
    load_events,
    load_labels,
    load_playbooks,
    load_portfolio,
)
from scripts.gen_playbooks import check as check_playbooks


def main() -> int:
    playbooks = load_playbooks()
    events = load_events()
    calm = load_calm_windows()
    portfolio = load_portfolio()
    labels = load_labels()

    errors = check_playbooks()
    errors += [f"{e.id}: 출처 URL 없음" for e in events if not e.sources]
    if not portfolio.synthetic:
        errors.append("portfolio: synthetic=true 필수")
    for label in labels:
        errors += [f"labels/{label.event_id}: {m}" for m in check_label_refs(label, playbooks, events, portfolio)]

    print(f"플레이북 {len(playbooks)} · 사건 {len(events)} · calm {len(calm)} · 포트폴리오 노드 {len(portfolio.nodes)} · 라벨 {len(labels)}")
    missing = sorted({e.id for e in events} - {lb.event_id for lb in labels})
    if missing:
        print(f"라벨 미작성 사건: {', '.join(missing)}")
    if errors:
        print("\n".join(["오류:"] + errors))
        return 1
    print("검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
