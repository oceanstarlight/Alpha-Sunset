import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """테스트마다 임시 데이터 디렉터리를 쓰고, 실제 API 키는 차단한다."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    monkeypatch.setenv("EMBED_MODEL", "test-embed")
    return tmp_path
