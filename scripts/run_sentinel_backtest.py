"""P3 Sentinel 재생: 6개 사건 ALERT 재현 + calm 구간 오경보 측정.

결과는 실제 실행값만 `data/backtest/sentinel_results.json`에 기록한다.
사용: python -m scripts.run_sentinel_backtest [--refresh]
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta

from app.agents.sentinel import merge_alerts, replay
from app.config import ROOT_DIR, load_config
from app.corpus import load_calm_windows, load_events
from app.data.fred import load_panel
from app.schemas import AlertLevel

OUT = ROOT_DIR / "data" / "backtest" / "sentinel_results.json"


def _series_ids() -> list[str]:
    m = load_config()["sentinel"]["market"]
    return m["series"] + [m["credit_spread"]["primary"], m["credit_spread"]["fallback"]]


def _first(results, level):
    hit = next((r for r in results if r.level == level), None)
    return hit.as_of.isoformat() if hit else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="FRED 캐시 갱신")
    args = parser.parse_args()

    cfg = load_config()["sentinel"]["replay"]
    panel = load_panel(_series_ids(), refresh=args.refresh)
    events = load_events()

    event_rows = []
    for e in sorted(events, key=lambda e: e.date):
        results = replay(panel, events, e.date - timedelta(days=cfg["days_before"]), e.date + timedelta(days=cfg["days_after"]))
        own = [r for r in results if e.id in r.keys]
        pre_watch = [r for r in results if r.as_of < e.date and r.market.active]
        first_alert = next((r for r in own if r.level == AlertLevel.ALERT), None)
        event_rows.append({
            "event_id": e.id,
            "event_date": e.date.isoformat(),
            "first_alert": first_alert.as_of.isoformat() if first_alert else None,
            "alert_triggered_by": first_alert.market.triggered if first_alert else [],
            "alert_days": sum(r.level == AlertLevel.ALERT for r in own),
            "merged_alerts": len([m for m in merge_alerts(own) if m.key == e.id]),
            "market_active_days_before_event": len(pre_watch),
            "first_market_active_before_event": pre_watch[0].as_of.isoformat() if pre_watch else None,
        })

    calm_rows = []
    for c in load_calm_windows():
        results = replay(panel, events, c.start, c.end)
        calm_rows.append({
            "window_id": c.id,
            "days": len(results),
            "alert_days": sum(r.level == AlertLevel.ALERT for r in results),
            "watch_days": sum(r.level == AlertLevel.WATCH for r in results),
            "first_watch": _first(results, AlertLevel.WATCH),
        })

    out = {
        "note": "백테스트 B는 사건 카드 기반. calm 구간에는 카드가 없어 ALERT가 구조적으로 0이며, WATCH(시장 신호 단독)를 오경보 지표로 함께 기록한다.",
        "config": {"replay": cfg, "market": load_config()["sentinel"]["market"], "card_active_days": load_config()["sentinel"]["news"]["card_active_days"]},
        "events": event_rows,
        "calm": calm_rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'사건':15s} {'사건일':11s} {'첫 ALERT':11s} {'ALERT일':>7s} {'병합':>4s} {'사전 A일':>8s}  트리거")
    for r in event_rows:
        print(f"{r['event_id']:15s} {r['event_date']:11s} {str(r['first_alert']):11s} {r['alert_days']:>7d} {r['merged_alerts']:>4d} {r['market_active_days_before_event']:>8d}  {','.join(r['alert_triggered_by'])}")
    print()
    for r in calm_rows:
        print(f"{r['window_id']:15s} 영업일 {r['days']:3d}  ALERT {r['alert_days']}  WATCH {r['watch_days']}")
    print(f"\n저장: {OUT.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
