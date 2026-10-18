import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """테스트마다 임시 데이터 디렉터리를 쓰고, 실제 API 키는 차단한다."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("EMBED_MODEL", "test-embed")
    return tmp_path


@pytest.fixture(autouse=True)
def reset_learner_toggle(monkeypatch):
    """학습 층 토글(모듈 상태)이 테스트 사이에 새지 않게 한다."""
    from app.agents import learner

    monkeypatch.setattr(learner, "_override", None)
