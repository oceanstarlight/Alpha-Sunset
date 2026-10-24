"""영구 감사 로그 (B5): 추가 전용 + 해시 체인 JSONL.

각 줄 = {seq, ts, source, action, actor, data, prev_hash, hash}. hash = sha256(hash를 뺀 줄의 정규화 JSON).
한 줄이라도 고치거나 지우면 그 줄부터 체인 검증이 깨진다.

출처(source)마다 파일을 따로 둔다 — 워크플로끼리 같은 파일을 동시에 커밋하다 충돌하지 않게.
- collect_signals / monitor_kr: GitHub Actions가 data/live와 함께 커밋 (공개 저장소 → 공개 데이터만 기록)
- app: Streamlit 사용 기록. 업로드 파일은 이름·내용 대신 해시·건수만 남긴다. 저장소에 커밋하지 않는다(.gitignore).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

GENESIS = "0" * 64


def audit_dir() -> Path:
    return get_settings().data_dir / "live" / "audit"


def path_for(source: str) -> Path:
    return audit_dir() / f"{source}.jsonl"


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(source: str) -> list[dict]:
    p = path_for(source)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _last(p: Path) -> dict | None:
    if not p.exists() or p.stat().st_size == 0:
        return None
    with open(p, "rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        buf = b""
        while pos > 0 and buf.count(b"\n") < 2:
            step = min(4096, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
    lines = [x for x in buf.splitlines() if x.strip()]
    return json.loads(lines[-1]) if lines else None


def append(action: str, data: dict[str, Any] | None = None, actor: str = "system", source: str = "app") -> dict:
    """한 줄 추가. 감사 기록 실패가 본 작업을 막지 않도록 호출부는 log()를 쓴다."""
    p = path_for(source)
    p.parent.mkdir(parents=True, exist_ok=True)
    last = _last(p)
    rec = {"seq": (last["seq"] + 1) if last else 1, "ts": datetime.now(timezone.utc).isoformat(), "source": source,
           "action": action, "actor": actor, "data": data or {}, "prev_hash": last["hash"] if last else GENESIS}
    rec["hash"] = _digest(rec)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def log(action: str, data: dict[str, Any] | None = None, actor: str = "system", source: str = "app") -> None:
    try:
        append(action, data, actor, source)
    except Exception as e:  # 디스크 문제 등 — 본 작업은 계속, 실패 사실만 출력
        print(f"감사 로그 기록 실패: {type(e).__name__}: {e}")


@dataclass
class Verification:
    source: str
    ok: bool
    n: int
    bad_seq: int | None = None
    reason: str = ""


def verify(source: str) -> Verification:
    prev, n = GENESIS, 0
    p = path_for(source)
    if not p.exists():
        return Verification(source, True, 0)
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return Verification(source, False, n, i, f"{i}번째 줄 JSON 손상")
        seq = rec.get("seq")
        if seq != n + 1:
            return Verification(source, False, n, seq, f"순번 불연속 (기대 {n + 1}, 실제 {seq}) — 삭제·삽입 의심")
        if rec.get("prev_hash") != prev:
            return Verification(source, False, n, seq, "앞 줄 해시와 불일치 — 앞 줄 변조·삭제 의심")
        if rec.get("hash") != _digest(rec):
            return Verification(source, False, n, seq, "줄 내용이 해시와 불일치 — 변조 의심")
        prev, n = rec["hash"], n + 1
    return Verification(source, True, n)


def sources() -> list[str]:
    d = audit_dir()
    return sorted(p.stem for p in d.glob("*.jsonl")) if d.exists() else []
