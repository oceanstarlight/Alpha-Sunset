import copy
import json
from pathlib import Path

import pytest

_KR_LATEST = Path(__file__).resolve().parents[1] / "data" / "live" / "kr_latest.json"


def kr_accumulating() -> dict:
    """커밋된 kr_latest.json을 '뉴스 기준선 축적 중' 상태로 고정한 사본.

    kr_latest.json은 수집기가 매일 덮어쓰므로, 그 값에 기대는 테스트는 날짜에 따라 깨진다.
    """
    kr = copy.deepcopy(json.loads(_KR_LATEST.read_text(encoding="utf-8")))
    news = kr["kr_news"]
    news.update(status="unavailable", clusters=[])
    for o in news["observations"].values():
        o.update(z=None, baseline_points=4)
    return kr


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """테스트마다 임시 데이터 디렉터리를 쓰고, 실제 API 키는 차단한다."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("EMBED_MODEL", "test-embed")
    for k in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_EMBED_MODEL"):
        monkeypatch.setenv(k, "")
    return tmp_path


@pytest.fixture(autouse=True)
def reset_learner_toggle(monkeypatch):
    """학습 층 토글(모듈 상태)이 테스트 사이에 새지 않게 한다."""
    from app.agents import learner

    monkeypatch.setattr(learner, "_override", None)
