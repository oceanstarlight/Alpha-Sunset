"""B3 예비 cron 중복 방지: 같은 종류의 실행이 최근 N분 안에 시작됐으면 skip=true.

정시 실행은 외부 cron(cron-job.org → workflow_dispatch)이 맡고, GitHub 예약 실행(schedule)은 외부 호출이
끊겼을 때만 대신 돈다. 실행 종류는 run-name(display_title)으로 구분한다 (예: "monitor-kr news" / "monitor-kr daily").

사용 (Actions): python scripts/recent_run.py --workflow monitor_kr.yml --title "monitor-kr news" --minutes 35
표준 라이브러리만 쓴다 (의존성 설치 전에 판단해 러너 시간을 아끼려고).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"


def list_runs(repo: str, workflow: str, token: str | None, per_page: int = 20) -> list[dict]:
    req = urllib.request.Request(f"{API}/repos/{repo}/actions/workflows/{workflow}/runs?per_page={per_page}",
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["workflow_runs"]


def recent_same_kind(runs: list[dict], title: str, minutes: int, now: datetime, exclude_id: int | None) -> dict | None:
    """최근 N분 안에 시작한 같은 종류 실행 (실패·취소는 제외 — 그런 경우엔 예비 실행이 돌아야 한다)."""
    since = now - timedelta(minutes=minutes)
    for r in runs:
        if r.get("id") == exclude_id or r.get("display_title") != title:
            continue
        if r.get("status") == "completed" and r.get("conclusion") != "success":
            continue
        started = datetime.fromisoformat((r.get("run_started_at") or r["created_at"]).replace("Z", "+00:00"))
        if started >= since:
            return r
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--minutes", type=int, required=True)
    args = ap.parse_args()
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_TOKEN")
    run_id = int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None
    try:
        hit = recent_same_kind(list_runs(repo, args.workflow, token), args.title, args.minutes,
                               datetime.now(timezone.utc), run_id)
    except Exception as e:  # 조회 실패 시 안전하게 실행 (중복 실행이 누락보다 낫다)
        print(f"최근 실행 조회 실패 → 실행: {type(e).__name__}: {e}")
        hit = None
    skip = hit is not None
    print(f"예비 실행 {'건너뜀' if skip else '진행'}: {args.title} 최근 {args.minutes}분"
          + (f" 안에 run {hit['id']} ({hit.get('event')}, {hit.get('status')})" if hit else " 안에 같은 종류 실행 없음"))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"skip={'true' if skip else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
