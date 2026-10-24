"""B3: 예비 cron 중복 방지 + 정시성 점검."""

from datetime import date, datetime, timedelta, timezone

from scripts.check_schedule import coverage, slots
from scripts.recent_run import recent_same_kind

NOW = datetime(2026, 10, 26, 1, 20, tzinfo=timezone.utc)  # 월 10:20 KST


def run(i, title, minutes_ago, status="completed", conclusion="success", event="workflow_dispatch"):
    t = (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": i, "display_title": title, "status": status, "conclusion": conclusion, "event": event,
            "created_at": t, "run_started_at": t}


def test_recent_external_run_skips_backup():
    runs = [run(1, "monitor-kr news", 20)]
    assert recent_same_kind(runs, "monitor-kr news", 35, NOW, exclude_id=99)["id"] == 1


def test_other_kind_or_old_or_failed_does_not_skip():
    runs = [run(1, "monitor-kr daily", 5), run(2, "monitor-kr news", 50),
            run(3, "monitor-kr news", 10, conclusion="failure"), run(4, "monitor-kr news", 1)]
    assert recent_same_kind(runs, "monitor-kr news", 35, NOW, exclude_id=4) is None  # 4는 자기 자신


def test_in_progress_run_counts():
    runs = [run(1, "collect-signals", 3, status="in_progress", conclusion=None)]
    assert recent_same_kind(runs, "collect-signals", 150, NOW, exclude_id=None) is not None


def test_slots_counts():
    mon = date(2026, 10, 26)
    assert len(slots("news", mon, mon)) == 24
    assert len(slots("news", date(2026, 10, 25), date(2026, 10, 25))) == 0  # 일요일
    assert len(slots("daily", mon, mon)) == 2 and len(slots("collect", mon, mon)) == 8
    assert slots("news", mon, mon)[0] == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)  # 08:00 KST


def test_coverage_on_time_and_delay():
    s = [datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc), datetime(2026, 10, 26, 0, 30, tzinfo=timezone.utc)]
    runs = [{"conclusion": "success", "created_at": "2026-10-26T00:03:00Z"},
            {"conclusion": "success", "created_at": "2026-10-26T01:10:00Z"},
            {"conclusion": "skipped", "created_at": "2026-10-26T00:31:00Z"}]
    c = coverage(s, runs, 15, NOW)
    assert c["slots"] == 2 and c["on_time"] == 1 and c["max_delay_min"] == 40.0
