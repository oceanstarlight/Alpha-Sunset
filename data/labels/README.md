# 백테스트 정답 라벨 (사용자 직접 설계)

- 파일명: `{event_id}.json` (예: `svb_2023.json`). `_template.json`을 복사해서 쓴다.
- 이 라벨은 **사람이 직접 설계한 합성 라벨**이다. 플레이북 작성자(Claude)와 라벨 설계자를 분리해 출제자=채점자 순환을 줄인다.
- 작성 후 `python -m scripts.validate_data`로 존재하지 않는 문서·조항·노드 참조가 없는지 확인한다.

| 필드 | 의미 | 값 |
|---|---|---|
| `event_id` | 사건 id | `data/events/*.json`의 `id` |
| `reaction_date` | 기관이 실제로 대응했어야 할 날짜 (lead_time 기준) | `YYYY-MM-DD` |
| `expected_docs` | 상위 3개 안에 들어야 할 문서 | `PB-LIQ` 등 `data/playbooks`의 `doc_id` |
| `expected_inapplicable_clauses` | 이 사건에 부적용이어야 하는 조항 | `PB-LIQ-06` 등 `clause_id` |
| `expected_gap_channels` | 어떤 문서도 다루지 못하는 채널 | `liquidity, credit_spread, counterparty, fx, commodity, supply_chain, rates, equity_vol, sanctions_trade, operational` |
| `expected_exposure_paths` | 상위 N 노출 경로에 나와야 할 포트폴리오 노드 | `data/portfolio.json`의 노드 `id` (예: `M-HANBIT`) |
