"""B2: LLM 제공자 전환 (gemini 기본 / openai_compatible / rule)."""

import json
from datetime import date

import httpx
import pytest
from pydantic import BaseModel

from app.agents.matcher import judge_clauses, rule_event, rule_judgment, structure_event
from app.llm.client import LLMClient, LLMUnavailableError, hash_embedding
from app.schemas import Channel, Clause, Duration, Event, EventType, Premises, Verdict


class Answer(BaseModel):
    value: int


EVENT = Event(id="e", title="은행 폐쇄", date=date(2023, 3, 10), summary="지역은행이 폐쇄되었다.",
              type=EventType.banking_stress, channels=[Channel.liquidity, Channel.counterparty], regions=["US"],
              duration=Duration.weeks, severity=4)


def clause(cid, types=(), channels=(), regions=()):
    return Clause(clause_id=cid, doc_id="D", text=f"{cid} 조항: 예금 잔액을 즉시 확인하고 분산한다.", owner_role="팀",
                  premises=Premises(event_types=list(types), channels=list(channels), regions=list(regions)))


def oa_client(handler, **kw):
    http = httpx.Client(base_url="http://llm.local/v1", transport=httpx.MockTransport(handler))
    c = LLMClient(provider="openai_compatible", model="local-model", embed_model="local-embed", http=http, **kw)
    c.min_interval = 0
    return c


def test_default_provider_is_gemini():
    c = LLMClient()
    assert c.provider == "gemini" and c.model == "test-model"


def test_env_switches_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "rule")
    assert LLMClient().provider == "rule"


def test_unknown_provider_rejected():
    with pytest.raises(ValueError):
        LLMClient(provider="nope")


def test_openai_compatible_generate_and_cache():
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append(body)
        assert req.url.path == "/v1/chat/completions" and body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"value": 7}\n```'}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

    c = oa_client(handler)
    assert c.generate("q", purpose="t", response_schema=Answer).value == 7
    assert c.generate("q", purpose="t", response_schema=Answer).value == 7  # 캐시
    assert len(seen) == 1 and "JSON 스키마" in seen[0]["messages"][0]["content"]


def test_openai_compatible_retries_invalid_json():
    replies = iter(["not json", '{"value": 3}'])

    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    assert oa_client(handler).generate("q", purpose="t", response_schema=Answer).value == 3


def test_openai_compatible_embed_order():
    def handler(req):
        assert req.url.path == "/v1/embeddings"
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]})

    assert oa_client(handler).embed(["a", "b"], purpose="t") == [[1.0, 0.0], [0.0, 1.0]]


def test_openai_compatible_chat_falls_back_to_empty():
    c = oa_client(lambda r: httpx.Response(500))
    assert not c.chat([], purpose="orchestrator", tools=[]).parts


def test_openai_compatible_requires_base_url():
    c = LLMClient(provider="openai_compatible", model="m")
    with pytest.raises(LLMUnavailableError):
        c.generate("q", purpose="t")


def test_rule_provider_embed_and_generate():
    c = LLMClient(provider="rule")
    a, b = c.embed(["은행 예금 인출", "은행 예금 인출 사태"], purpose="t")
    assert len(a) == 256 and abs(sum(x * x for x in a) - 1) < 1e-9
    assert sum(x * y for x, y in zip(a, b)) > sum(x * y for x, y in zip(a, hash_embedding("관세 부과")))
    with pytest.raises(LLMUnavailableError):
        c.generate("q", purpose="t")
    assert not c.chat([], purpose="o", tools=[]).parts


def test_rule_judgment_levels():
    assert rule_judgment(clause("A", [EventType.banking_stress], [Channel.liquidity], ["US"]), EVENT).verdict == Verdict.applicable
    assert rule_judgment(clause("B", [EventType.banking_stress], [Channel.fx]), EVENT).verdict == Verdict.partial
    assert rule_judgment(clause("C", [EventType.pandemic], [Channel.liquidity]), EVENT).verdict == Verdict.partial
    j = rule_judgment(clause("D", [EventType.pandemic], [Channel.fx]), EVENT)
    assert j.verdict == Verdict.not_applicable and j.confidence == 0.3 and j.evidence_quote
    assert rule_judgment(clause("E", [EventType.banking_stress], [Channel.liquidity], ["KR"]), EVENT).verdict == Verdict.partial


def test_judge_clauses_uses_rules_without_llm_calls():
    out = judge_clauses(LLMClient(provider="rule"), EVENT, [clause("A", [EventType.banking_stress], [Channel.liquidity])])
    assert out[0].verdict == Verdict.applicable and "규칙 판정" in out[0].mismatch_reasons[0]


def test_rule_event_structuring():
    e = structure_event(LLMClient(provider="rule"), "미국 지역은행 뱅크런\n예금 인출 급증", "live_x", date(2026, 10, 24))
    assert e.type == EventType.banking_stress and Channel.liquidity in e.channels
    assert rule_event("트럼프 관세 부과 발표", "x", date(2025, 4, 2)).type == EventType.trade_policy
    assert rule_event("아무 일 없음", "x", date(2025, 4, 2)).type == EventType.other
