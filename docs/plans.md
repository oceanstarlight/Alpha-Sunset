# Alpha Sunset — plans.md

KIC AI 에이전트 공모전(주제: 투자·금융 업무 혁신 AI Agent, 문제 자유 정의) 본선 MVP.

## 주제
**위기 사건 ↔ 내부 대응문서 적합도 판단 + 보유 자산 노출 경고 Agent. 문서 우선순위는 알파 썬셋으로 최적화.**

### 문제
- 기관의 위기 대응 문서(리스크 대응 매뉴얼, 과거 위기 사후보고서, 리스트 대응 문서, 리포트)는 여러 문서·부서에 파편화돼 있다.
- 사건이 터졌을 때 어떤 문서가 지금 맞는지 판단하기 어렵다. 문서는 작성 당시 사건의 전제에 묶여 있다 (예: 코로나 당시 매뉴얼은 유동성 위기 전제 → 지정학·공급망 충격에는 일부 조항만 유효).
- 위탁운용사·펀드·카운터파티를 거친 간접 노출은 종목 매핑만으로 보이지 않는다.

### 에이전트 기능
1. **상시 감시**: 스크립트가 변동성과 자금시장 지표(신용스프레드, 금리, 환율, 원자재 등)를 상시 관찰한다. 전 세계 또는 특정 국가의 큰 사건이 함께 확인될 때만 경보를 올린다 (이중 조건, 오경보 억제).
2. **적합도 판단 (핵심 차별점)**: 경보 시 사건과 문서 조항의 전제를 대조해 조항별 적용/부분적용/부적용을 판정하고, 어떤 문서도 다루지 않는 **공백**을 찾는다. 적용 조항의 조치 항목으로 **대응 방안**을 제시한다.
3. **노출 경고**: 기관의 자금·자산(MVP는 가상 포트폴리오)을 입력하면, 사건과 연관된 투자 기관·펀드·자산·카운터파티를 **보유 경로(출처)**와 **위험도**로 추적하고 특히 주의할 항목을 알린다.
4. **알파 썬셋(문서 우선순위 최적화)**: 큰 사건은 자주 발생하므로 에이전트가 특정 문서를 반복 인용하게 된다. 이 이력으로 자주 유용했던 문서의 우선순위를 올리고 거의 쓰이지 않는 문서는 내려 대응 품질을 높인다. **문서를 삭제·폐기하지 않고 검색 우선순위만 조정한다.**
   - 인용 빈도 단독 사용 금지: 많이 인용된 문서가 더 자주 인용되는 편향과, 드물게 쓰이지만 결정적인 문서(보험형·규제 필수)가 밀려나는 문제가 있다. 그래서 사건 유형별 집계 + 사용자 피드백 + 탐색 보너스 + protected 하한을 결합한다 (5.4).
   - 초기 데이터 오염 방지를 위해 기본 OFF. 로그는 격리 기록만 하고, 백테스트 검증 후 ON.

### 한 줄 메시지
문서를 찾아주는 AI가 아니라 **"이 문서가 이번 사건에 맞는지, 어디가 안 맞고 무엇이 비어 있는지 알려주는 AI"**. 최종 결정은 사람 승인.

### MVP 범위
- 입력은 합성 데이터(가상 포트폴리오, 재구성한 대응문서). 스키마는 실제 환경과 동일하게 설계해 입력만 교체하면 동작.
- 검증은 과거 사건 백테스트 (8장).

## 0. 불변 규칙
- UI/출력/문서는 한국어. 코드 식별자는 영어.
- 모든 판정(verdict)은 `clause_id` + 근거 인용문을 포함. 근거 없으면 `uncertain`. 검증 실패 시 재시도 2회 후 `uncertain`.
- 에이전트는 제안만 한다. 문서 삭제/폐기/자동 확정 금지. 승인은 사람(UI).
- 합성 데이터는 `synthetic: true` 필수. 합성 사실을 UI에 표시.
- 결과 수치(백테스트 등)는 실제 실행값만 기록. 임의 작성 금지.
- 비밀키는 로컬 `.env`, 배포 `st.secrets`. 커밋 금지.
- LLM 호출은 `llm/client.py` 단일 래퍼만 사용. 모든 호출을 `llm_calls` 테이블에 기록(ts, model, in/out tokens, purpose, cache_hit). 운영진 API 사용 내역 요청 대비.
- 외부 데이터는 `data/SOURCES.md`에 기록: 이름, URL, 수집일, 라이선스/약관, 전처리. 제출 필수 항목.
- 학습 층은 `LEARNER_ENABLED=false` 기본. 로그(`shadow_log`)는 항상 기록, 점수 반영은 플래그 ON일 때만.
- 백테스트/시뮬레이션은 `data/sandbox.db`, 라이브는 `data/live.db`. 섞지 않는다.

## 1. 스택 (확정)
| 영역 | 선택 |
|---|---|
| 언어 | Python 3.11 |
| 서비스 계층 | Pydantic v2 + 순수 Python 함수. FastAPI 사용 안 함 |
| UI | Streamlit. 서비스 함수를 직접 호출 |
| LLM | Gemini API, `google-genai`. 모델명은 env(`GEMINI_MODEL`, 기본 `gemini-3.5-flash-lite`), structured output(`response_schema`), temperature 0 |
| 임베딩 | env(`EMBED_MODEL`, 기본 `gemini-embedding-001`). 가용 여부 확인 후 아니면 Gemini 임베딩 최신 모델로 교체 |
| 벡터 | ChromaDB (persistent, `data/chroma`) |
| DB | SQLite (`live.db`, `sandbox.db`) |
| 그래프 | networkx |
| 데이터 | pandas, httpx |
| 설정 | `config.yaml` (임계치·가중치) |
| 배포 | **Streamlit Community Cloud (확정)**. GitHub 저장소 연결, 공개 데모 URL 필수 |

LLM 응답 캐시: 입력 해시 → SQLite(`data/llm_cache.db`). 백테스트 재현성/비용 절감용.

### 배포 제약 (Streamlit Community Cloud)
- 단일 Streamlit 프로세스만 실행. 별도 API 서버·Docker 불가 → UI가 `app/services.py` 함수를 직접 import.
- 파일시스템 비영속: 재시작 시 `live.db`·`chroma`·런타임 로그 초기화. 앱 시작 시 저장소의 `data/` 커밋본으로 재구성한다.
- 저장소에 커밋: `playbooks`, `portfolio`, `events`, `labels`, `holdings` parquet, `fred` CSV, `llm_cache.db`(임베딩·판정 캐시), `backtest_results.json`. 용량 제한 확인 후 필요한 범위만.
- 백테스트 재생은 커밋된 캐시로 동작(키 없이도 재현). 라이브 모드·캐시 미스만 Gemini 호출.
- 데모 중 쌓이는 피드백/`shadow_log`는 비영속이어도 무방(데모 한정). 영속화는 보류.
- 비활동 시 앱이 슬립됨 → 시연 전 접속해 깨워둘 것. 리소스 제한이 있으므로 모델 로컬 로딩 금지(전부 API 호출).
- 의존성은 `requirements.txt`(버전 고정). Python 버전은 앱 설정에서 3.11 선택.

## 2. 디렉터리
```
alpha_sunset/
  config.yaml  .env.example  requirements.txt  README.md  .streamlit/config.toml
  data/
    SOURCES.md  source_notes/   # 공개 보고서 요지(재구성 근거)
    playbooks/*.json            # 합성 대응문서
    portfolio.json              # 가상 포트폴리오
    holdings/                   # N-PORT 전처리 parquet
    events/*.json               # 큐레이션 사건 카드
    labels/*.json               # 백테스트 정답
    fred/*.csv                  # 캐시
  app/
    schemas.py  config.py  db.py
    llm/client.py  llm/cache.py
    data/fred.py  data/gdelt.py  data/nport.py
    agents/sentinel.py  matcher.py  exposure.py  orchestrator.py  learner.py
    briefing.py
    services.py          # UI가 호출하는 진입 함수 모음
  ui/streamlit_app.py
  scripts/gen_playbooks.py  build_holdings.py  run_backtest.py
  tests/
```

## 3. 스키마 (`app/schemas.py`)
Enum
- `EventType`: liquidity_crisis, credit_event, banking_stress, geopolitical, supply_chain, trade_policy, pandemic, rate_shock, fx_shock, regulatory, other
- `Channel`: liquidity, credit_spread, counterparty, fx, commodity, supply_chain, rates, equity_vol, sanctions_trade, operational
- `Duration`: shock, weeks, months, structural
- `Verdict`: applicable, partial, not_applicable, uncertain

`Event`: id, title, date, summary, type: EventType, channels: list[Channel], regions: list[str], sectors: list[str], asset_classes: list[str], entities: list[str], duration, severity(1–5), sources: list[url]

`Clause`: clause_id, doc_id, text, premises{event_types, channels, regions, asset_classes, duration, conditions}, actions: list[str], owner_role, protected: bool, protected_reason: regulatory|insurance|None

`Playbook`: doc_id, title, version, year, origin_event, synthetic: bool, source_refs: list[str], clauses: list[Clause]

`ClauseJudgment`: clause_id, verdict, mismatch_reasons: list[str], evidence_quote, confidence(0–1)

`DocFit`: doc_id, fit_score, n_applicable, n_partial, n_not, n_uncertain, judgments: list[ClauseJudgment]

`MatchResult`: event_id, doc_fits: list[DocFit], gaps: list[Channel], low_confidence: bool

`ExposurePath`: nodes: list[str] (Institution→Manager/Counterparty→Fund→Holding→Region/Sector), weight, relevance, uncertainty, risk_score, why: str

`Briefing`: run_id, event, alert_level, match: MatchResult, exposure_top: list[ExposurePath], actions_to_check: list[str], evidence_refs, trace_id

`Feedback`: run_id, doc_id, label: useful|not_fit, user_id, ts

## 4. 데이터

### 4.1 소스
| 용도 | 소스 | 비고 |
|---|---|---|
| 시장 신호 A | FRED API | 시리즈: `VIXCLS`, `BAMLH0A0HYM2`(최근 3년, 이전은 `BAA10Y`), `T10Y2Y`, `DGS10`, `DEXKOUS`, `DCOILWTICO`, `DTWEXBGS`. 로컬 CSV 캐시 |
| 사건 신호 B (라이브) | GDELT DOC 2.0 API | **최근 약 3개월만 조회 가능(확인할 것)**. 라이브 모드 전용 |
| 사건 (백테스트) | `data/events/*.json` 큐레이션 | 공개 출처 요약+URL. GDELT 대체 |
| 펀드 보유 | SEC EDGAR N-PORT 분기 데이터셋 | 요청 시 User-Agent에 연락처 포함. 필요한 펀드만 추출해 parquet화 |
| 문서 재구성 근거 | 국제기구·중앙은행·금융당국 공개 보고서 | `data/source_notes/`에 요지만 저장, 원문 복제 금지, URL 기록 |

### 4.2 백테스트 사건 (6개 + 평상 구간)
| id | 사건 | 비고 |
|---|---|---|
| gfc_2008 | 2008 리먼 사태 + 한국 외환시장 불안 | 한국 사례 |
| covid_2020 | 2020 코로나 충격 (한국 증시 급락·공매도 금지 포함) | 한국 사례 |
| ru_ua_2022 | 2022 러시아-우크라이나 전쟁 | |
| legoland_2022 | 2022 레고랜드 사태(국내 단기자금시장 경색) | 한국 사례 |
| svb_2023 | 2023 SVB 사태 | |
| tariff_2025 | 2025 관세 충격 | |
| calm_* | 평상 구간 3개 (오경보 측정용, 사건 없는 분기) | |

사건 카드와 한국 사례 사실관계는 반드시 공개 출처로 확인 후 URL 기재. 확인 불가한 내용은 쓰지 않는다.

### 4.3 합성 플레이북 (`data/playbooks`)
- 12개 문서, 문서당 약 8조항 (총 약 100조항). 모두 `synthetic: true`.
- 생성: `scripts/gen_playbooks.py` — `source_notes` 입력 → Gemini로 조항 초안(전제·조치 포함) → 사람 검수.
- 주제: 유동성 위기, 신용·카운터파티 부도, 은행 시스템 위기, 지정학·제재, 환율 급변(한국 외환), 팬데믹 BCP, 무역정책 충격, 금리 급등, 원자재 충격, 단기자금시장 경색(국내), 위탁운용사 사고(protected), 규제 보고(protected).
- 의도적 설계: 문서는 `origin_event`의 전제에 묶여 있어 다른 사건에는 일부 조항만 유효해야 함 (적합도 판정 시연용). 일부 오래된 문서·중복 조항 포함.
- `protected` 조항: 규제 필수, 보험형. 우선순위가 낮아져도 후보에서 제외 금지.

### 4.4 가상 포트폴리오 (`data/portfolio.json`)
- 범용 기관투자자. 노드 유형: 직접 보유(ETF/채권), 외부 위탁운용사(가상 이름 6개, 각 mandate를 공개 펀드 하나로 proxy 매핑), 카운터파티(가상 이름 5개, 스왑/레포).
- proxy 매핑 노드는 `uncertainty=0.3`, 직접 보유는 `0`, 카운터파티 노출은 `0.5`.
- 사건별 노출이 드러나도록 펀드 선택 (예: 지역은행, 한국·EM 채권, 하이일드, 에너지, 중국 관련). 보유 내역은 사건일 이전 가장 가까운 분기 스냅샷 사용.
- 모든 비중은 가상값이며 `synthetic: true`.

## 5. 에이전트

공통: 도구는 순수 함수로 구현, 입출력은 스키마 준수.

### 5.1 Sentinel (`agents/sentinel.py`)
- A: 각 FRED 시리즈의 1일 변화율의 z-score (trailing 252영업일). 활성 조건: `|z| ≥ 2.5`인 시리즈 ≥ 2개 또는 어느 하나 `|z| ≥ 4`.
- B: 주제 쿼리별 기사량이 30일 기준선 대비 z ≥ 3 AND 서로 다른 출처 ≥ 20. 유사 기사는 군집화해 단일 사건으로.
- 등급: A+B = `ALERT` (Matcher 호출), 하나만 = `WATCH`, 없음 = `NONE`. 같은 군집은 72h 내 1건으로 병합.
- 임계치는 `config.yaml`. 백테스트로 조정.
- 백테스트 모드: B는 사건 카드의 `date` 이전 정보만 허용(미래 정보 누수 금지). A는 해당일까지의 데이터만 사용.

### 5.2 Matcher (`agents/matcher.py`)
1. 사건 구조화: 텍스트 → `Event` (structured output). 백테스트는 카드의 구조화값을 LLM으로 재추출하고 검증.
2. 후보: 사건 요약 임베딩으로 조항 top-30 검색 (+ `protected` 조항 항상 포함).
3. 판정: 조항별로 `premises` ↔ `Event` 항목 대조 → `ClauseJudgment`. 배치 호출(조항 5~10개씩). 근거 인용문 필수.
4. `fit_score(doc) = (n_applicable + 0.5·n_partial) / (n_applicable + n_partial + n_not)`. `uncertain`은 분모 제외, 개수는 별도 표시.
5. 공백: `event.channels` 중 `applicable`/`partial` 조항의 `premises.channels`에 포함되지 않은 채널 = gap.
6. 분기: 최고 `fit_score < 0.4`이면 쿼리를 확장해 1회 재검색. 평균 confidence < 0.5이면 `low_confidence=true`.
7. 순위: `LEARNER_ENABLED=false` → `fit_score` 순. true → 5.4의 보정 적용.

### 5.3 Exposure (`agents/exposure.py`)
- 그래프: Institution → (Manager | Counterparty | Direct) → Fund → Holding(issuer) → Region/Sector.
- 사건 연관도 `relevance(0–1)`: 사건의 entities/regions/sectors/asset_classes와 노드 속성의 겹침을 규칙 기반으로 계산. 이름 매칭 실패 시에만 LLM 보조.
- `risk_score = weight × relevance × (1 − 0.5·uncertainty)`. 상위 N=10 경로 반환, 각 경로에 `why` 한 줄 생성(LLM, 경로 속성만 입력).
- 불확실 경로 비율 > 0.5이면 Orchestrator가 추가 보유 내역 조회 후 재계산(1회).

### 5.4 Learner (`agents/learner.py`) — 기본 OFF
대상 단위: `(doc_id, event_type)`.
- `cite_norm = decayed_count / max_decayed_count(event_type)`, 감쇠 반감기 180일(시뮬레이션 시간 기준).
- `fb = (useful + 1) / (useful + not_fit + 2)`.
- `recency = exp(−Δdays / 180)` (마지막 인용 기준).
- `explore = c · sqrt(ln(N_type + 1) / (n_doc + 1))`, `c = 0.2`.
- `priority = 0.4·cite_norm + 0.4·fb + 0.2·recency + explore` (0–1로 클립).
- 보정: `final = fit_score × (1 + 0.3·(priority − 0.5))`. `protected` 문서는 `priority` 하한 0.5, 순위와 무관하게 후보 유지.
- 입력: `shadow_log`만. 모드(`live|backtest|sim`)별로 분리 집계. 라이브 점수에 sandbox 로그 유입 금지.
- `shadow_log(event_id, doc_id, event_type, cited, rank, feedback, mode, ts)` — 플래그와 무관하게 항상 기록.
- 토글: `set_learner_enabled`, 변경 이력 기록.

### 5.5 Orchestrator (`agents/orchestrator.py`)
- Gemini function calling 루프, `max_steps=10`. 도구: `get_market_signals`, `search_events`, `retrieve_clauses`, `judge_clauses`, `compute_exposure`, `get_priority`, `build_briefing`.
- 하드 제약(코드로 강제): `build_briefing`은 `judge_clauses`와 `compute_exposure` 실행 후에만 허용. 위 5.2-6, 5.3 분기 규칙 적용.
- 모든 도구 호출·입출력 요약을 `traces` 테이블에 저장(`trace_id`). UI에서 조회.
- 출력: `Briefing`. `actions_to_check`는 `applicable/partial` 조항의 `actions`와 `owner_role`을 집계(LLM은 문장 정리만).

## 6. 서비스 함수 (`app/services.py`, UI가 직접 호출)
| 함수 | 설명 |
|---|---|
| `get_signals()` | 최신 시그널 A/B/C 및 등급 (기본: 일일 수집기 결과 `data/live/signals_latest.json`, `refresh=True`면 직접 조회) |
| `run_live()` | 현재 사건 탐지 → Briefing |
| `run_replay(event_id)` | 백테스트 사건 재생 → Briefing (sandbox) |
| `get_briefing(run_id)` | 브리핑 조회 |
| `get_trace(trace_id)` | 도구 호출 trace |
| `submit_feedback(Feedback)` | `Feedback` 저장 + `shadow_log` 갱신 |
| `get_priority()` | 문서 우선순위(플래그 무관하게 계산 가능, 반영은 플래그) |
| `set_learner_enabled(bool)` | LEARNER_ENABLED 변경 |
| `get_backtest_results()` | 최신 백테스트 지표 |

## 7. UI (Streamlit, 6탭)
0. **세계 금융 지도** (메인): 세계 지도 위에 원으로 사건 지역(빨강, 심각도)·보유 비중(파랑)·영향도(주황, 노출 경로 risk_score 합)·GDELT 보도 국가(보라, 라이브)를 표시. pydeck ScatterplotLayer.
1. **감시**: 시그널 A/B 차트, 등급, 최근 경보.
2. **브리핑**: 사건 요약 → 문서별 적합도(조항 단위 적합/부분/부적합 + 근거 + 불일치 사유) → 공백 채널 → 노출 상위 경로(그래프) → 확인 항목 → 출처. 합성 데이터 배지 표시.
3. **승인**: 문서별 유용/부적합 피드백, 승인·반려.
4. **백테스트**: 사건별 지표 표, 재생 버튼.
5. **학습 층**: ON/OFF 토글, 문서 우선순위 변화, ON/OFF 비교 결과.

## 8. 백테스트 (`scripts/run_backtest.py`)
정답 라벨 `labels/{event_id}.json`: `reaction_date`, `expected_docs[]`, `expected_inapplicable_clauses[]`, `expected_gap_channels[]`, `expected_exposure_paths[]`. 라벨은 직접 설계(합성)임을 README에 명시.

지표
| 지표 | 정의 |
|---|---|
| lead_time | `reaction_date` − 경보일 (일) |
| doc_top3_hit | 라벨 문서가 상위 3개에 포함된 비율 |
| clause_PR | 부적합 조항 판정 precision/recall |
| gap_PR | 공백 채널 precision/recall |
| path_recall | 라벨 노출 경로 중 상위 N에서 탐지된 비율 |
| false_alarms | calm 구간 ALERT 수 |
| learner_delta | ON − OFF의 `doc_top3_hit` 차이 |

학습 층 검증: 사건을 시간순으로 재생. 각 사건 후 `expected_docs` 기반 시뮬레이션 피드백을 `sandbox.db`의 `shadow_log`에 기록. OFF/ON 각각 실행해 비교. 결과는 "시뮬레이션 기반"으로 표기(라벨 기반 피드백은 순환 위험 있음을 README에 명시).

결과 출력: `data/backtest_results.json` + UI 탭 4·5.

## 9. 마일스톤 (순서대로, 완료 기준 포함)
- [ ] **M0 스캐폴딩**: 디렉터리, config, db, `llm/client.py`(캐시·로그), 스키마, 테스트 틀. *완료: `pytest` 통과, LLM 호출이 `llm_calls`에 기록됨*
- [ ] **M1 데이터**: FRED 수집·캐시, N-PORT 전처리, GDELT 클라이언트, `SOURCES.md` 작성. *완료: 7개 시리즈 CSV, 선택 펀드 parquet*
- [ ] **M2 합성 코퍼스**: 플레이북 12개, 사건 카드 6개+calm 3개, 포트폴리오, 라벨. *완료: 스키마 검증 통과, 전 문서 synthetic 표기, 출처 URL 기재*
- [ ] **M3 Sentinel**: z-score·이중 트리거·등급·군집. *완료: 6개 사건 모두 ALERT 재현 시도, calm 구간 오경보 측정*
- [ ] **M4 Matcher**: 구조화·검색·판정·공백·분기. *완료: 6개 사건 MatchResult 생성, 근거 없는 판정 0건*
- [ ] **M5 Exposure**: 그래프·relevance·risk_score. *완료: 사건별 상위 경로와 `why` 생성*
- [ ] **M6 Orchestrator + Briefing**: 함수 호출 루프, 하드 제약, trace 저장. *완료: `run_replay(event_id)`가 Briefing 반환*
- [ ] **M7 서비스 계층 + UI + 배포**: `services.py`, 5탭, Streamlit Community Cloud 배포(`st.secrets` 설정, 커밋 데이터로 시작 시 재구성). *완료: 외부 접속 가능한 데모 URL, 재시작 후에도 정상 기동*
- [ ] **M8 백테스트**: 지표 6종 산출, 임계치 보정. *완료: `backtest_results.json` 생성*
- [ ] **M9 Learner**: 점수 엔진, `shadow_log`, 토글, ON/OFF 비교. *완료: `learner_delta` 산출, 라이브 점수에 sandbox 미유입 테스트 통과*
- [ ] **M10 제출물**: README(실행법·환경·데이터 출처·합성 명시), 발표자료용 결과 요약.

## 10. 테스트 필수 항목
- 스키마 round-trip, 근거 없는 verdict 거부.
- 백테스트 모드에서 사건일 이후 데이터 접근 시 실패(누수 방지).
- `build_briefing` 선행 도구 미실행 시 거부.
- `LEARNER_ENABLED=false`일 때 순위가 `fit_score`와 동일.
- `protected` 조항이 항상 후보에 포함.
- live/sandbox DB 분리.

## 11. 기본값으로 진행하는 결정 (바꾸려면 여기 수정)
- 배포 호스트: Streamlit Community Cloud (확정).
- 서비스명 표기: Alpha Sunset.
- 임계치·가중치는 초기값으로 시작, M8에서 조정.
- 신용스프레드 신호: `BAMLH0A0HYM2`(HY OAS)는 FRED 공개 범위가 최근 3년뿐 → 이력이 충분한 시점(최근 3년)에는 HY OAS, 그 이전은 `BAA10Y`(Moody's Baa−10년물)로 대체.
- `gfc_2008`은 N-PORT 공개 데이터(2019년~)가 없어 노출 분석(Exposure)에서 제외. Sentinel·Matcher 백테스트에는 포함.
- 백테스트 시그널 B는 사건 카드 `date`부터 14일간 활성(`card_active_days`).
- N-PORT는 분기 데이터셋 대신 펀드별 NPORT-P 공시 XML을 개별 수집(비용·용량 절감). 스냅샷은 사건일 이전에 공개된 공시만 사용.
- Matcher 근거 검증: `evidence_quote`가 조항 원문 또는 사건 요약의 실제 문구가 아니면 재질의, 재시도 소진 시 `uncertain`.
- Matcher 백테스트는 카드의 구조화값을 사용하고, LLM 재추출은 일치도 검증용으로만 기록.
- Exposure 이름 매칭: 규칙은 법인 접미사를 뗀 토큰 완전 일치만, LLM 보조는 민간 기관만(중앙은행·정부·감독기관·국제기구 제외). 사건 기관과 같은 발행자 보유는 상위 N과 별도로 `entity_paths`에 표시.
- Exposure 지역: 사건 regions의 `EU`는 유럽 전체(영국·스위스·노르웨이 포함), `EM`은 신흥국 그룹으로 매핑.
- Orchestrator: 도구는 인자 없이 실행 컨텍스트의 상태를 사용(LLM이 사건 데이터를 조작하지 못하게). LLM 루프가 브리핑까지 못 가면 남은 단계를 코드가 마저 실행. 함수 호출 응답도 대화 해시로 캐시해 재현.
- 백테스트 입력은 사건 카드의 `summary_as_of`·`entities_as_of`(사건일 당일까지 알려진 사실 + 당일 FRED 값)만 사용. 원래 `summary`는 UI 표시·사후 참고용.
- 오경보 대리 지표: 백테스트 B가 카드 기반이라 평상 구간 ALERT는 구조적으로 0 → 사건 ±180일 제외 영업일의 시그널 A 단독 발동률을 함께 보고.
- 라벨: 에이전트 결과·사후 요약이 없는 격리 폴더에서 별도 서브에이전트(Sonnet)가 초안 작성 → 사용자 검수. 사건일에 아직 발표되지 않은 정책 대응을 전제로 한 조항은 부적용(보수적).
- 검증 규칙 변경은 사전 등록(`data/backtest/ablation/preregistration*.json`)으로 실행 전에 커밋하고, 결과를 보고 바꾸려면 새 버전으로 등록한다. 임계치·가중치는 라벨 6개로 튜닝하지 않는다.
- 자금 흐름 신호 C (보류 해제): FRED 주간 MMF·예금·해외 공적 미국채 보관·지준, 공표 시차 반영. 등급 v2 = ALERT ⇔ B ∧ (A ∨ C). 한국 데이터(KRX 외국인 순매수)는 인증키 확보 후 추가.
- 데이터 제외는 품질 보고서(커버리지·공백·시차·평상 발동률)로만 판단하고 사건 적중 성적은 쓰지 않는다.
- 공백 규칙 v2: partial 판정은 조항 전제 사건유형이 이번 사건 유형과 같을 때만 채널을 다룬 것으로 본다.
- 2단계 운영 (사전 등록 v3): 1단계 자금 이상 알림(A ∨ C, 5영업일 중 2일 이상) → 2단계 사건 확정(B) 시 대응안(브리핑). 1차 지표는 선행 알림일·대응안 지연·평상시 알림 비율이며, 선행 알림은 평상일 기준선과 함께 보고한다. 조기 사건 카드는 추가하지 않는다.
- Learner (사전 등록 v4): 5.4 공식 그대로 구현, 순위 보정은 Orchestrator `get_priority`에서 ON일 때만. 검증은 라벨 기반 시뮬레이션(순환 위험 명시), 1회 재생 + 반복 2회 재생.
- 플레이북: 기획 단계 합성 데이터로 수용(사용자 검수 2026-10-18, 실제 규정 기반 아님). 추후 실제 공개 규정·기관 문서 기반 조항으로 확장·교체 가능 (교체 시 라벨·지표 재계산).
- 라이브 GDELT: Streamlit Cloud 공유 IP에서 요청 제한(429)·연결 끊김이 잦아 ① 클라이언트가 429·연결 끊김을 점증 대기(간격 10초 × 시도 횟수, 최대 4회) 후 재시도하고 ② 조회 실패는 '사건 없음'과 구분해 `ok / partial / unavailable`(판단 불가)로 표시하며 ③ GitHub Actions 일일 수집기(매일 07:07 KST)가 결과를 `data/live/`에 커밋한다. UI는 수집 결과를 기본으로, 직접 조회는 보조로 쓴다.
- 세계 금융 지도: GDELT GEO 2.0 API가 404라 사건 발생 위치 지도는 쓰지 않고, DOC API 기사의 `sourcecountry`(보도 매체 국가)를 표시한다. 국가 좌표는 Google 공개 국가 중심점 표. 지역 묶음은 EU만 대표 좌표(브뤼셀), EM·GLOBAL은 표로만.
- Gemini 무료 등급 대응: 분당 14회로 제한, 429 시 서버 안내 시간만큼, 503·500은 점증 대기 후 재시도(`config.yaml` `llm`).

## 12. 보류 사항 (MVP 제외)
- ~~자금 유출입 감시 신호~~ → P8에서 FRED 주간 자금 흐름(시그널 C)으로 구현. 한국 일간 데이터만 인증키 대기.
- 피드백·`shadow_log` 영속 저장소 (데모는 비영속).
- 실제 기관 문서·포트폴리오 연동.
