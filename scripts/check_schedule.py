"""B3 정시성 점검: 예정 시각(슬롯)마다 제때 실행이 있었는지 GitHub Actions 실행 이력으로 센다.

- monitor-kr news: 평일 08:00~19:30 KST 30분마다 (24슬롯/일), 슬롯 시작 후 15분 안에 시작하면 정시
- monitor-kr daily: 평일 07:00·16:40 KST, 20분 안
- collect-signals: 매일 3시간마다 (KST 00:05부터), 30분 안
공개 저장소라 토큰 없이 조회된다 (GITHUB_TOKEN이 있으면 사용).

사용: python -m scripts.check_schedule --days 7 [--until 2026-10-24]
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.recent_run import API

KST = ZoneInfo("Asia/Seoul")
REPO = os.environ.get("GITHUB_REPOSITORY", "oceanstarlight/Alpha-Sunset")


def fetch_runs(workflow: str, since: datetime, token: str | None = None) -> list[dict]:
    out, page = [], 1
    while True:
        url = (f"{API}/repos/{REPO}/actions/workflows/{workflow}/runs?per_page=100&page={page}"
               f"&created=>={since.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   **({"Authorization": f"Bearer {token}"} if token else {})})
        with urllib.request.urlopen(req, timeout=30) as r:
            runs = json.load(r)["workflow_runs"]
        out += runs
        if len(runs) < 100:
            return out
        page += 1


def slots(kind: str, start: date, end: date) -> list[datetime]:
    """[start, end] KST 날짜 범위의 예정 시각 (UTC)."""
    out = []
    d = start
    while d <= end:
        weekday = d.weekday() < 5
        if kind == "news" and weekday:
            out += [datetime.combine(d, time(8, 0), KST) + timedelta(minutes=30 * i) for i in range(24)]
        elif kind == "daily" and weekday:
            out += [datetime.combine(d, time(7, 0), KST), datetime.combine(d, time(16, 40), KST)]
        elif kind == "collect":
            out += [datetime.combine(d, time(0, 5), KST) + timedelta(hours=3 * i) for i in range(8)]
        d += timedelta(days=1)
    return [s.astimezone(timezone.utc) for s in out]


def started(run: dict) -> datetime:
    return datetime.fromisoformat((run.get("run_started_at") or run["created_at"]).replace("Z", "+00:00"))


def coverage(slot_times: list[datetime], runs: list[dict], tolerance_min: int, now: datetime) -> dict:
    """슬롯별로 [슬롯, 슬롯+허용) 안에 시작한 실행(건너뛴 예비 제외 — 성공 실행만)이 있으면 정시."""
    ok_runs = sorted(started(r) for r in runs if r.get("conclusion") == "success")
    due = [s for s in slot_times if s + timedelta(minutes=tolerance_min) <= now]
    hit, delays = 0, []
    for s in due:
        nxt = next((t for t in ok_runs if t >= s), None)
        if nxt is not None and nxt < s + timedelta(minutes=tolerance_min):
            hit += 1
        if nxt is not None:
            delays.append((nxt - s).total_seconds() / 60)
    delays.sort()
    return {"slots": len(due), "on_time": hit, "rate": round(hit / len(due), 3) if due else None,
            "median_delay_min": round(delays[len(delays) // 2], 1) if delays else None,
            "max_delay_min": round(delays[-1], 1) if delays else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--until", type=date.fromisoformat, default=None, help="KST 마지막 날짜 (기본: 오늘)")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    end = args.until or now.astimezone(KST).date()
    start = end - timedelta(days=args.days - 1)
    since = datetime.combine(start, time(0, 0), KST).astimezone(timezone.utc)
    token = os.environ.get("GITHUB_TOKEN")
    kr = fetch_runs("monitor_kr.yml", since, token)
    gl = fetch_runs("collect_signals.yml", since, token)
    title = lambda r: r.get("display_title") or ""  # noqa: E731
    report = {
        "period_kst": [start.isoformat(), end.isoformat()],
        # run-name 도입 전 실행은 제목이 'monitor-kr'뿐이라 news·daily 모두에 센다
        "monitor-kr news": coverage(slots("news", start, end), [r for r in kr if title(r) in ("monitor-kr news", "monitor-kr")], 15, now),
        "monitor-kr daily": coverage(slots("daily", start, end), [r for r in kr if title(r) in ("monitor-kr daily", "monitor-kr")], 20, now),
        "collect-signals": coverage(slots("collect", start, end), gl, 30, now),
        "runs_by_event": {w: {e: sum(r["event"] == e and r.get("conclusion") == "success" for r in rs)
                              for e in ("workflow_dispatch", "schedule")} for w, rs in (("monitor-kr", kr), ("collect-signals", gl))},
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
