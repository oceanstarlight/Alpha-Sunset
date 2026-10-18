# Alpha Sunset

> 위기 사건 ↔ 내부 대응문서 적합도 판단 + 보유 자산 노출 경고 AI Agent
> KIC AI 에이전트 공모전 본선 MVP

문서를 찾아주는 AI가 아니라, **"이 문서가 이번 사건에 맞는지, 어디가 안 맞고 무엇이 비어 있는지 알려주는 AI"**.

**데모**: https://alpha-sunset.streamlit.app

## 주요 기능
1. **상시 감시** — 시장 지표 + 글로벌 사건 이중 조건으로 경보 (오경보 억제)
2. **적합도 판단** — 사건과 대응문서 조항의 전제를 대조해 적용/부분적용/부적용 판정, 공백 탐지
3. **노출 경고** — 위탁운용사·펀드·카운터파티를 거친 간접 노출 경로와 위험도 추적
4. **알파 썬셋** — 인용 이력·피드백으로 문서 검색 우선순위 최적화 (삭제·폐기 없음)

최종 결정은 사람이 승인한다.

## 스택
Python 3.11 · Streamlit · Gemini API · ChromaDB · SQLite

## 참고
- 계획: [`docs/plans.md`](docs/plans.md)
- 진행 현황: [`docs/Current.md`](docs/Current.md)
- MVP는 합성 데이터(가상 포트폴리오·재구성 대응문서)로 동작한다.

## 로컬 실행
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # GEMINI_API_KEY, SEC_USER_AGENT 입력 (백테스트 재생은 키 없이도 캐시로 동작)
.venv/bin/streamlit run ui/streamlit_app.py
.venv/bin/pytest -q
```

> 상세 내용(데이터 출처·합성 명시·백테스트 결과)은 제출 단계(P10)에서 보강 예정.
