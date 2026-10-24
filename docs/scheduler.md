# 정시 실행 설정 (B3) — cron-job.org → GitHub Actions

## 왜 필요한가 (원인 → 근거 → 결과)
- **원인**: GitHub Actions 예약 실행(`schedule`)은 혼잡하면 늦어지거나 아예 생략된다 (GitHub 문서에 명시된 동작).
- **근거**: `python -m scripts.check_schedule --days 6 --until 2026-10-23` (2026-10-18~23 실측)

  | 작업 | 예정 | 제때 실행 (허용 오차) | 지연 중앙값 / 최대 |
  |---|---|---|---|
  | 한국 감시 30분 주기 | 120회 | **11회 (9%)** (15분) | 100분 / 340분 |
  | 한국 시장·자금 갱신 (07:00·16:40) | 10회 | **0회** (20분) | 120분 / 177분 |
  | 글로벌 수집 3시간 주기 | 48회 | **3회 (6%)** (30분) | 209분 / 1157분 |

- **결과**: 정시 실행은 외부 무료 cron(cron-job.org)이 GitHub API로 워크플로를 직접 호출(`workflow_dispatch`)한다. 기존 `schedule`은 **예비**로만 남는다. 같은 종류의 실행이 최근에 있었으면 예비 실행은 스스로 취소된다 (`scripts/recent_run.py`).

## 1. GitHub 토큰 만들기 (이 저장소의 Actions 실행 권한만)
1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
2. 설정
   - Token name: `alpha-sunset-cron`
   - Expiration: 최대 1년 (만료일을 달력에 적어둔다 — 만료되면 정시 실행이 멈추고 예비 실행만 돈다)
   - Repository access: **Only select repositories** → `oceanstarlight/Alpha-Sunset`
   - Repository permissions: **Actions → Read and write** (나머지는 건드리지 않는다)
3. 토큰을 복사한다. 이 토큰으로는 이 저장소의 워크플로를 실행·취소하는 것만 할 수 있다 (코드 수정·푸시 불가).
   채팅·저장소에 붙여넣지 않는다.

## 2. cron-job.org 작업 4개 만들기
cron-job.org 가입 → Dashboard → **Create cronjob**. 4개 모두 공통 설정:

- **Advanced → Request method**: `POST`
- **Advanced → Headers**
  - `Authorization`: `Bearer <1단계 토큰>`
  - `Accept`: `application/vnd.github+json`
  - `X-GitHub-Api-Version`: `2022-11-28`
- **Advanced → Time zone**: `Asia/Seoul`
- **Notifications**: "execution fails" 켜기 (호출이 실패하면 메일로 알려준다)

| 이름 | URL | 실행 시각 (KST) | Request body |
|---|---|---|---|
| monitor-kr news | `https://api.github.com/repos/oceanstarlight/Alpha-Sunset/actions/workflows/monitor_kr.yml/dispatches` | 월~금 08:00~19:30, 매시 0·30분 | `{"ref":"main","inputs":{"daily":"false"}}` |
| monitor-kr daily am | 위와 같음 | 월~금 07:00 | `{"ref":"main","inputs":{"daily":"true"}}` |
| monitor-kr daily pm | 위와 같음 | 월~금 16:40 | `{"ref":"main","inputs":{"daily":"true"}}` |
| collect-signals | `https://api.github.com/repos/oceanstarlight/Alpha-Sunset/actions/workflows/collect_signals.yml/dispatches` | 매일 00:05부터 3시간마다 (00·03·06·09·12·15·18·21시 5분) | `{"ref":"main"}` |

실행 시각은 Schedule → **Custom**에서 고른다 (news: Days of week 월~금, Hours 8~19, Minutes 0·30).

## 3. 확인
1. 각 작업의 **Test run** → 응답 `204 No Content`이면 성공. 그다음 GitHub Actions 탭에 `monitor-kr news` 같은 이름으로 실행이 뜬다.
   - `401`: 토큰이 틀렸거나 만료됨
   - `403`/`404`: 토큰 권한(Actions write)이나 저장소 선택이 빠짐, 또는 URL 오타
   - `422`: body 오류 (`ref`가 `main`인지, `daily` 값이 `"true"`/`"false"`인지 확인)
2. 하루 뒤 정시성을 다시 잰다: `python -m scripts.check_schedule --days 1`
   - 목표: 세 작업 모두 제때 실행 95% 이상. `runs_by_event`에서 `workflow_dispatch`가 대부분이어야 한다.

## 동작 규칙
- 외부 호출(`workflow_dispatch`)은 항상 실행된다. 한 번에 하나만 돌고(`concurrency`), 앞 실행이 끝날 때까지 다음 호출은 기다린다.
- 예비 실행(`schedule`)
  - 한국 감시: 매시 17분, daily는 07:07·16:47
  - 글로벌 수집: 3시간마다 37분
  - 같은 종류의 실행이 최근 35분(daily 60분, 글로벌 150분) 안에 시작됐으면 그 예비 실행은 취소한다
- 외부 cron이 끊기면(토큰 만료·서비스 장애) 예비 실행이 대신 돈다. 이때 정시성은 예전 수준으로 떨어진다.
- 비용: 저장소가 공개라 Actions 시간은 무료이고, cron-job.org도 무료다.
