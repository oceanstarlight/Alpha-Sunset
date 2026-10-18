# Current — 진행 현황

> 기준 문서: [`plans.md`](./plans.md) · P 번호 = plans.md 9장 마일스톤 번호(M0~M10)
> 마지막 갱신: 2026-10-17

## 범례
| 표시 | 의미 |
|---|---|
| ✅ | 완료 |
| 🔄 | 진행 중 |
| ⏳ | 예정 |
| ⏸️ | 보류 |
| 🗑️ | 폐기 |

## 한눈에 보기
| P | 내용 | 상태 |
|---|---|---|
| P0 | 스캐폴딩 | ✅ 완료 |
| P1 | 외부 데이터 수집 | ✅ 완료 |
| P2 | 합성 코퍼스 | 🔄 진행 중 (라벨·검수 대기) |
| P3 | Sentinel (상시 감시) | ✅ 완료 |
| P4 | Matcher (적합도 판단) | ✅ 완료 (라벨 채점 대기) |
| P5 | Exposure (노출 경고) | ✅ 완료 |
| P6 | Orchestrator + Briefing | ✅ 완료 |
| P7 | 서비스 계층 + UI + 배포 | ✅ 완료 |
| P8 | 백테스트 | ⏳ 예정 |
| P9 | Learner (알파 썬셋) | ⏳ 예정 |
| P10 | 제출물 | ⏳ 예정 |

---

## P0 — 스캐폴딩 ✅
- ✅ 디렉터리 구조 생성 (plans.md 2장, 저장소 루트 기준)
- ✅ `config.yaml`, `.env.example`, `requirements.txt`(버전 고정), `.streamlit/config.toml`
- ✅ `app/schemas.py` — Enum·모델 전체 (plans.md 3장)
- ✅ `app/config.py` — env → `st.secrets` 순 조회
- ✅ `app/db.py` — `live.db` / `sandbox.db` 분리
- ✅ `app/llm/client.py` 단일 래퍼 + `llm/cache.py` + `llm_calls` 로깅
- ✅ 테스트: 스키마 round-trip, 근거 없는 verdict 거부, live/sandbox 분리, LLM 로깅·캐시·재시도
- **완료 기준**: `pytest` 통과 (23 passed), LLM 호출이 `llm_calls`에 기록됨 (fake SDK로 검증, 실제 API 호출은 키 설정 후 확인)

## P1 — 외부 데이터 수집 ✅
- ✅ FRED 8개 시리즈 수집 + CSV 캐시 (`app/data/fred.py`, BAA10Y 포함)
- ✅ SEC N-PORT: 프록시 펀드 8개 × 스냅샷 6개(사건 5 + live) = 48개 parquet (`app/data/nport.py`, `scripts/build_holdings.py`)
  - 분기 데이터셋(수백 MB) 대신 펀드별 NPORT-P XML만 수집, 사건일 이전 공시만 사용(누수 방지), gfc_2008 제외
- ✅ GDELT DOC 2.0 클라이언트 (`app/data/gdelt.py`, 요청 간격 6초·429 재시도)
- ✅ `data/SOURCES.md` 작성
- **완료 기준**: 시리즈 CSV ✅, 선택 펀드 parquet ✅

## P2 — 합성 코퍼스 🔄
- ✅ `source_notes/` 공개 자료 요지 12개 (확인된 사실만 기록)
- ✅ 플레이북 12개 / 96조항 (protected 10개: regulatory 6, insurance 4) — Claude 초안, `scripts/gen_playbooks.py`로 검증
- ⏳ 플레이북 사람 검수
- ✅ 사건 카드 6개 (공개 출처 URL 확인) + calm 구간 3개 (2014Q2, 2017Q4, 2024Q1 — FRED 기준 선정)
- ✅ 가상 포트폴리오 (직접 6, 위탁운용사 6, 카운터파티 5)
- ⏳ 백테스트 정답 라벨 — **사용자 직접 설계** (`data/labels/README.md`, `_template.json`)
- ✅ `app/corpus.py` 로더, `scripts/validate_data.py` 전체 검증, 테스트
- **완료 기준**: 스키마 검증 통과, 전 문서 `synthetic: true`, 출처 URL 기재 → 라벨·검수 남음

### P2에서 발견한 P1 이슈
- ⚠️ FRED `BAMLH0A0HYM2`(HY 스프레드)는 공개 범위가 최근 3년뿐 → 과거 백테스트용 대체 시리즈 필요
- ⚠️ SEC N-PORT 공개 데이터는 2019년 이후 → `gfc_2008` 보유내역 스냅샷 확보 불가

## P3 — Sentinel (상시 감시) ✅
- ✅ 시그널 A: FRED z-score (252영업일, 당일 제외), 신용스프레드 HY OAS→BAA10Y 대체
- ✅ 시그널 B: 라이브 GDELT 기사량 z-score + 출처 수 + 제목 군집화 / 백테스트 사건 카드
- ✅ 이중 트리거 등급 (`ALERT` / `WATCH` / `NONE`), 72h 병합
- ✅ 백테스트 미래 정보 누수 차단 (`AsOfPanel`) + 테스트
- ✅ 재생 스크립트 `scripts/run_sentinel_backtest.py` → `data/backtest/sentinel_results.json`
- **완료 기준**: 6개 사건 모두 ALERT 재현 ✅, calm 3구간 ALERT 0·WATCH 0
- ⚠️ calm 구간은 같은 시그널 A 규칙으로 골랐기 때문에 오경보 0은 순환적 결과. P8에서 무작위 평상 구간 추가 측정 필요
- ⚠️ 백테스트 B는 카드 date부터 켜지므로 사건일보다 앞선 ALERT는 구조적으로 불가 (사전 경고는 WATCH 일수로 기록)
- ⚠️ GDELT 실제 호출이 현재 환경에서 429(요청 제한)로 실패 → 응답 형식은 앞선 정상 응답으로 확인, 라이브 검증은 P7 배포 환경에서 재확인

## P4 — Matcher (적합도 판단) ✅
- ✅ 사건 구조화 (`structure_event`) + 백테스트 카드 재추출 검증 (`verify_card`, 카드 값으로 판정)
- ✅ ChromaDB 검색 top-30 + protected 조항 항상 포함 (`app/retrieval.py`, 코퍼스 지문 바뀌면 재색인)
- ✅ 조항별 배치 판정: 근거 인용문이 조항 원문·사건 요약의 실제 문구인지 검증, 실패 조항만 재시도 2회 → `uncertain`
- ✅ `fit_score`, 공백 채널, `fit_score < 0.4` 재검색, `low_confidence`, 순위(Learner OFF = fit_score 순)
- ✅ `scripts/run_matcher.py` → `data/backtest/match/*.json`, `match_summary.json`
- ✅ LLM 래퍼에 무료 등급 분당 요청 제한(14회)·429 대기 재시도 추가, 캐시로 키 없이 재현 확인
- **완료 기준**: 6개 사건 MatchResult 생성 ✅, 근거 없는 판정 0건 ✅
- ⚠️ 6개 사건 모두 공백 채널 0 → partial도 '다룸'으로 보는 규칙이 느슨할 수 있음. 라벨 나오면 P8에서 조정
- ⚠️ 판정 품질(top3 적중, 부적합 조항 P/R)은 라벨이 있어야 채점 가능
- ⚠️ 사건 카드 요약에 사건일 이후 사실(예: 11월 환율 고점)이 포함됨 → 판정 입력 누수 가능, P8에서 사건일 기준 요약 분리 검토

## P5 — Exposure (노출 경고) ✅
- ✅ networkx 그래프: 기관 → 직접/위탁운용사/카운터파티 → 프록시 펀드 → 보유(발행자·국가별 묶음) → 지역·업종
- ✅ 규칙 기반 `relevance` (지역 0.4·업종 0.35·자산군 0.25, 유럽·신흥국 지역 그룹 매핑)
- ✅ 이름 매칭: 규칙(토큰 완전 일치) → 실패한 민간 기관만 LLM 보조, 공공기관(중앙은행·정부·감독기관) 매칭 제외
- ✅ `risk_score = weight × relevance × (1 − 0.5·uncertainty)`, 상위 10개 + `why`(LLM, 경로 속성만 입력)
- ✅ 사건 기관과 같은 발행자 보유는 `entity_paths`로 별도 표시 (예: svb_2023 → KRE의 SVB Financial Group, Signature Bank)
- ✅ 불확실 경로 비율 계산 (`needs_requery`) — 추가 조회 후 재계산은 P6 Orchestrator에서 연결
- ✅ `scripts/run_exposure.py` → `data/backtest/exposure/*.json` (gfc_2008 제외)
- **완료 기준**: 사건별 상위 경로와 `why` 생성 ✅ (5개 사건)
- ⚠️ 순위가 큰 직접 보유(국채·대형주 ETF)에 쏠림: 사건 지역에 GLOBAL이 있으면 모든 노드가 지역 일치로 잡힘. ru_ua_2022에서 EMB의 러시아·우크라이나 국채 경로가 30위·38위 → **P8에서 라벨 기준으로 조정 (사용자 결정)**

## P6 — Orchestrator + Briefing ✅
- ✅ Gemini 함수 호출 루프 (`max_steps=10`, 도구 7개). LLM은 호출 순서만 정하고 도구 입력·상태는 코드가 보유
- ✅ 하드 제약: `build_briefing`은 `judge_clauses`·`compute_exposure` 실행 후에만 허용 + 테스트
- ✅ 분기 규칙: fit_score < 0.4 확장 재검색 1회, 불확실 경로 비율 > 0.5 보유내역 재조회 1회(백테스트는 추가 공시 없음을 기록)
- ✅ LLM이 브리핑까지 못 가면 남은 단계를 코드가 정해진 순서로 실행 (trace에 `fallback` 기록)
- ✅ `traces`·`briefings` 테이블 저장, `get_trace`·`get_briefing`
- ✅ `actions_to_check`: applicable/partial 조항의 조치를 담당 역할별로 모으고 중복 조치는 조항 번호만 합침, LLM은 문장 정리만
- ✅ `scripts/run_replay.py` → `data/backtest/briefings/*.json`, 캐시로 키 없이 재현 확인
- **완료 기준**: `run_replay(event_id)`가 Briefing 반환 ✅ (6개 사건, LLM이 7단계 모두 권장 순서로 호출, fallback 0회)
- ⚠️ 재생 기준일 = 사건 카드 date라 covid_2020·tariff_2025는 WATCH (시장 신호가 다음 날 켜짐, P3 결과와 동일)
- ⚠️ 확인 항목이 사건당 12~35개로 많음 → UI(P7)에서 담당 역할별 묶음 표시 예정

## P7 — 서비스 계층 + UI + 배포 ✅
- ✅ `app/services.py` 9개 함수 + `load_saved_briefing`, `record_approval`
  - `run_live`: FRED 갱신 + GDELT 뉴스 군집 → LLM 구조화 → 라이브 브리핑 (live DB, 최신 보유내역)
  - `submit_feedback`: feedback + shadow_log (브리핑 모드에 맞춰 live/backtest 분리)
  - `set_learner_enabled`: P9 전에는 ON 거부, 모든 시도 기록
- ✅ 브리핑 생성 시 `shadow_log`에 문서별 인용·순위 상시 기록
- ✅ Streamlit 5탭 (`ui/streamlit_app.py`): 감시(경보 재생·FRED 차트·라이브 조회) / 브리핑(적합도·근거·공백·노출 그래프·담당별 확인 항목·출처·trace) / 승인(문서 피드백·승인/반려) / 백테스트 / 학습 층, 합성 데이터 배지
- ✅ 콜드 스타트 확인: 새로 받은 저장소에서 키 없이 `run_replay` 성공 (Chroma·sandbox.db 자동 재구성)
- ✅ AppTest·서비스 테스트 추가
- ✅ Streamlit Community Cloud 배포: https://alpha-sunset.streamlit.app (사용자 확인)
- ⏳ 재시작(Reboot) 후 정상 기동 재확인
- ⏳ 라이브 GDELT 호출을 배포 환경에서 재확인 (현재 세션은 429)
- **완료 기준**: 외부 접속 가능한 데모 URL ✅, 재시작 후에도 정상 기동 (콜드 스타트 로컬 검증 ✅, 배포 환경 Reboot 확인 대기)

## P8 — 백테스트 ⏳
- ⏳ (P3·P4·P5 이월) 무작위 평상 구간 오경보 측정, 공백 채널 규칙, 사건일 기준 요약 분리, Exposure 순위(GLOBAL 점수·핵심 경로 표시) 조정
- ⏳ `scripts/run_backtest.py` 지표 산출 (lead_time, doc_top3_hit, clause_PR, gap_PR, path_recall, false_alarms)
- ⏳ 임계치·가중치 보정 (`config.yaml`)
- **완료 기준**: `backtest_results.json` 생성 (실제 실행값만 기록)

## P9 — Learner (알파 썬셋) ⏳
- ⏳ 우선순위 점수 엔진 (cite_norm + fb + recency + explore, protected 하한)
- ⏳ `shadow_log` 상시 기록 (모드별 분리 집계)
- ⏳ `set_learner_enabled` 토글 + 변경 이력
- ⏳ ON/OFF 비교 → `learner_delta`
- ⏳ 테스트: OFF 시 순위 = `fit_score`, sandbox 로그 라이브 미유입
- **완료 기준**: `learner_delta` 산출, 라이브 점수에 sandbox 미유입 테스트 통과

## P10 — 제출물 ⏳
- ⏳ README 정식본 (실행법·환경·데이터 출처·합성 명시·라벨 순환 위험 명시)
- ⏳ 발표자료용 결과 요약
- ⏳ `llm_calls` 기반 API 사용 내역 정리

---

## ⏸️ 보류 (MVP 제외 — plans.md 12장)
- ⏸️ 자금 유출입(ETF flow 등) 감시 신호 — 무료·안정적 공개 데이터 미정, 자금시장 지표로 대체
- ⏸️ 피드백·`shadow_log` 영속 저장소 — 데모는 비영속
- ⏸️ 실제 기관 문서·포트폴리오 연동

## 🗑️ 폐기 (채택하지 않기로 한 것)
- 🗑️ FastAPI 서비스 계층 — Streamlit이 서비스 함수 직접 호출로 대체
- 🗑️ 별도 API 서버·Docker — Streamlit Community Cloud 제약
- 🗑️ 모델 로컬 로딩 — 리소스 제한, 전부 API 호출
- 🗑️ 인용 빈도 단독 우선순위 — 편향 문제로 복합 점수(5.4)로 대체
