"""대응 문서 입력 검증 → data/ingest/doc_verification.json.

합성 플레이북을 워드·PDF로 렌더링한 샘플(정답 있음)로 조항 분해·담당·보호·전제 속성을 비교한다.
방식 2가지: 규칙만 / LLM+검증. LLM 응답은 캐시되어 키 없이 재현된다.
사용: python scripts/verify_doc_ingest.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import ROOT_DIR  # noqa: E402
from app.ingest.documents import ingest_document  # noqa: E402

SAMPLES = ROOT_DIR / "data" / "ingest" / "doc_samples"
OUT = ROOT_DIR / "data" / "ingest" / "doc_verification.json"


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s)


def jaccard(a: set, b: set) -> float | None:
    return None if not a and not b else len(a & b) / len(a | b)


def compare(res, truth: list[dict]) -> dict:
    got = res.playbook.clauses
    match = {}
    for ti, t in enumerate(truth):
        hit = next((c for c in got if _n(t["text"]) in _n(c.text)), None)
        if hit:
            match[ti] = hit
    used = {id(c) for c in match.values()}
    jac_e = [jaccard(set(truth[i]["event_types"]), {e.value for e in c.premises.event_types}) for i, c in match.items()]
    jac_c = [jaccard(set(truth[i]["channels"]), {x.value for x in c.premises.channels}) for i, c in match.items()]
    jac_e, jac_c = [x for x in jac_e if x is not None], [x for x in jac_c if x is not None]
    return {
        "clauses_truth": len(truth), "clauses_extracted": len(got),
        "clause_recall": round(len(match) / len(truth), 4),
        "clause_precision": round(sum(id(c) in used for c in got) / len(got), 4) if got else None,
        "owner_accuracy": round(sum(c.owner_role == truth[i]["owner_role"] for i, c in match.items()) / max(len(match), 1), 4),
        "protected_accuracy": round(sum(c.protected == truth[i]["protected"] for i, c in match.items()) / max(len(match), 1), 4),
        "event_types_jaccard": round(sum(jac_e) / len(jac_e), 4) if jac_e else None,
        "channels_jaccard": round(sum(jac_c) / len(jac_c), 4) if jac_c else None,
    }


def main() -> None:
    truth = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))["docs"]
    try:
        from app.llm.client import LLMClient

        llm = LLMClient(db_mode="sandbox")
    except Exception as e:
        print(f"LLM 없음: {e}")
        llm = None
    results = {}
    for fname, doc in (("PB-BANK.docx", "PB-BANK"), ("PB-LIQ.pdf", "PB-LIQ")):
        data = (SAMPLES / fname).read_bytes()
        results[fname] = {"rule": compare(ingest_document(data, fname), truth[doc])}
        if llm is not None:
            r = ingest_document(data, fname, llm=llm)
            results[fname]["llm"] = compare(r, truth[doc]) | {"chain": r.chain}
        for mode, m in results[fname].items():
            print(fname, mode, {k: v for k, v in m.items() if k != "chain"})
    OUT.write_text(json.dumps({"generated_at": date.today().isoformat(), "results": results}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")


if __name__ == "__main__":
    main()
