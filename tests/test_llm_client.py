from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.db import connect
from app.llm.client import LLMClient, LLMResponseError, LLMUnavailableError


class Answer(BaseModel):
    value: int


class FakeModels:
    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.generate_calls = 0
        self.embed_calls: list[list[str]] = []

    def generate_content(self, model, contents, config):
        self.generate_calls += 1
        assert config.temperature == 0
        return SimpleNamespace(
            text=self.texts.pop(0),
            usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3),
        )

    def embed_content(self, model, contents):
        self.embed_calls.append(list(contents))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(len(c)), 1.0]) for c in contents])


def make_client(texts=(), mode="live"):
    fake = FakeModels(list(texts))
    client = LLMClient(db_mode=mode, sdk_client=SimpleNamespace(models=fake))
    client.min_interval = 0  # 테스트에서는 요청 간격 대기 생략
    return client, fake


def llm_calls(mode="live"):
    conn = connect(mode)
    rows = [dict(r) for r in conn.execute("SELECT * FROM llm_calls ORDER BY id")]
    conn.close()
    return rows


def test_call_is_logged_with_tokens():
    client, _ = make_client(['{"value": 1}'])
    assert client.generate("q", purpose="test", response_schema=Answer) == Answer(value=1)
    rows = llm_calls()
    assert len(rows) == 1
    assert rows[0]["model"] == "test-model"
    assert (rows[0]["in_tokens"], rows[0]["out_tokens"]) == (12, 3)
    assert rows[0]["purpose"] == "test"
    assert rows[0]["cache_hit"] == 0


def test_second_call_hits_cache_and_is_logged():
    client, fake = make_client(['{"value": 7}'])
    client.generate("q", purpose="test", response_schema=Answer)
    assert client.generate("q", purpose="test", response_schema=Answer) == Answer(value=7)
    assert fake.generate_calls == 1
    assert [r["cache_hit"] for r in llm_calls()] == [0, 1]


def test_invalid_response_is_retried():
    client, fake = make_client(["not json", '{"value": 2}'])
    assert client.generate("q", purpose="test", response_schema=Answer) == Answer(value=2)
    assert fake.generate_calls == 2
    assert len(llm_calls()) == 2


def test_gives_up_after_max_retries():
    client, fake = make_client(["bad"] * 3)
    with pytest.raises(LLMResponseError):
        client.generate("q", purpose="test", response_schema=Answer)
    assert fake.generate_calls == 3  # 최초 1회 + 재시도 2회


def test_plain_text_generation():
    client, _ = make_client(["안녕"])
    assert client.generate("q", purpose="test") == "안녕"


def test_no_api_key_and_cache_miss_raises():
    client = LLMClient()
    with pytest.raises(LLMUnavailableError):
        client.generate("q", purpose="test")


def test_embed_caches_per_text():
    client, fake = make_client()
    assert client.embed(["ab", "c"], purpose="emb") == [[2.0, 1.0], [1.0, 1.0]]
    assert client.embed(["c", "def"], purpose="emb") == [[1.0, 1.0], [3.0, 1.0]]
    assert fake.embed_calls == [["ab", "c"], ["def"]]


def test_sandbox_calls_logged_to_sandbox_only():
    client, _ = make_client(['{"value": 1}'], mode="sandbox")
    client.generate("q", purpose="backtest", response_schema=Answer)
    assert len(llm_calls("sandbox")) == 1
    assert llm_calls("live") == []


def test_rate_limit_error_is_retried(monkeypatch):
    import app.llm.client as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    client, fake = make_client(['{"value": 4}'])

    class RateLimited(Exception):
        code = 429

    calls = {"n": 0}
    original = fake.generate_content

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("Please retry in 1.5s.")
        return original(**kw)

    fake.generate_content = flaky
    assert client.generate("q", purpose="test", response_schema=Answer) == Answer(value=4)
    assert calls["n"] == 2
