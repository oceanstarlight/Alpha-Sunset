"""입력 변환 검증 → data/ingest/verification.json.

- 합성 3종: 정답(truth.json)과 행 단위 비교 (금액·국가·자산군·보유 형태)
- 실제 공개 파일: 국민연금 국내주식(커밋됨), iShares IVV(약관상 커밋하지 않음 — 있으면 함께 검증)
매핑 방식 2가지를 모두 돌린다: 규칙만 / LLM+규칙. LLM 응답은 캐시에 남아 키 없이 재현된다.
사용: python scripts/verify_ingest.py [--ishares 경로]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT_DIR  # noqa: E402
from app.ingest.pipeline import ingest  # noqa: E402

SAMPLES = ROOT_DIR / "data" / "ingest" / "samples"
OUT = ROOT_DIR / "data" / "ingest" / "verification.json"


def compare(df, truth: dict, mapped: set[str]) -> dict:
    t = {h["name"]: h for h in truth["holdings"]}
    got = {r["name"]: r for r in df.to_dict("records")}
    common = [n for n in t if n in got]

    def acc(field):
        if field not in mapped:
            return {"checked": 0, "accuracy": None, "note": "파일에 해당 열 없음"}
        vals = [(got[n].get(field), t[n][field]) for n in common if got[n].get(field) not in (None, "")]
        return {"checked": len(vals), "accuracy": round(sum(a == b for a, b in vals) / len(vals), 4) if vals else None}

    amt_err = [abs(got[n]["amount"] - t[n]["amount"]) / t[n]["amount"] for n in common if got[n].get("amount") is not None]
    return {
        "rows_expected": truth["n"], "rows_converted": len(df), "rows_matched": len(common),
        "amount_max_rel_error": round(max(amt_err), 8) if amt_err else None,
        "total_amount_rel_error": round(abs(df["amount"].sum() - truth["total_amount"]) / truth["total_amount"], 8),
        "weight_sum": round(float(df["weight"].sum()), 6),
        "country": acc("country"), "asset_class": acc("asset_class"), "holding_type": acc("holding_type"),
        "isin_filled": int(df["isin"].notna().sum()), "local_code_filled": int(df["local_code"].notna().sum()),
    }


def run(path: Path, llm, truth: dict | None) -> dict:
    res, prof = ingest(path, llm=llm, use_preset=False)
    out = {"mapping": [{"field": c.field, "source": c.source, "multiplier": c.multiplier, "percent": c.percent, "reason": c.reason}
                       for c in res.spec.columns],
           "defaults": res.spec.defaults, "method": res.spec.method, "notes": res.spec.notes,
           "chain": res.chain, "dropped": len(res.dropped)}
    if truth:
        out["vs_truth"] = compare(res.holdings, truth, {c.field for c in res.spec.columns})
    else:
        out["summary"] = {"rows": len(res.holdings), "total_amount": float(res.holdings["amount"].sum()),
                          "weight_sum": round(float(res.holdings["weight"].sum()), 6),
                          "country_filled": int(res.holdings["country"].notna().sum())}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ishares", type=Path, default=None)
    args = ap.parse_args()
    truth = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))
    try:
        from app.llm.client import LLMClient

        llm = LLMClient(db_mode="sandbox")
    except Exception as e:
        print(f"LLM 없음: {e}")
        llm = None
    files = [(SAMPLES / "broker_balance.xlsx", truth), (SAMPLES / "manager_report.xlsx", truth),
             (SAMPLES / "dataguide_style.xlsx", truth), (SAMPLES / "unusual_headers.xlsx", truth),
             (SAMPLES / "nps_domestic_equity_2025.csv", None)]
    if args.ishares and args.ishares.exists():
        files.append((args.ishares, None))
    results = {}
    for path, t in files:
        results[path.name] = {"rule": run(path, None, t)}
        if llm is not None:
            results[path.name]["llm_rule"] = run(path, llm, t)
        for mode, r in results[path.name].items():
            s = r.get("vs_truth") or r.get("summary")
            print(f"{path.name:32s} {mode:9s} {json.dumps(s, ensure_ascii=False)}")
    OUT.write_text(json.dumps({"generated_at": date.today().isoformat(), "results": results}, ensure_ascii=False, indent=1,
                              default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
