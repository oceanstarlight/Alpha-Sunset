"""LLM 단일 래퍼. 모든 LLM 호출은 이 모듈을 거치고 `llm_calls`에 기록된다.

제공자(B2, config llm.provider / env LLM_PROVIDER):
- gemini (기본): Google Gemini SDK. 함수 호출(chat) 지원.
- openai_compatible: OpenAI 호환 /chat/completions·/embeddings (Ollama·vLLM·사내 게이트웨이). chat은 미지원 →
  빈 응답을 돌려 Orchestrator가 정해진 순서(complete_deterministically)로 진행한다.
- rule: LLM 없음. 임베딩은 해시 n-gram, generate는 LLMUnavailableError → 호출부가 규칙 판정으로 대체.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings, load_config
from app.db import DbMode, connect
from app.llm.cache import LLMCache, make_key

T = TypeVar("T", bound=BaseModel)


RETRYABLE_CODES = {429, 500, 503}
PROVIDERS = ("gemini", "openai_compatible", "rule")
HASH_DIM = 256


class LLMUnavailableError(RuntimeError):
    """API 키가 없고 캐시에도 없는 호출."""


class LLMResponseError(RuntimeError):
    """재시도 후에도 응답이 스키마 검증에 실패."""


class LLMClient:
    def __init__(
        self,
        db_mode: DbMode = "live",
        sdk_client: Any | None = None,
        cache: LLMCache | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        provider: str | None = None,
        http: Any | None = None,
    ):
        settings = get_settings()
        self.db_mode = db_mode
        self.provider = provider or settings.llm_provider
        if self.provider not in PROVIDERS:
            raise ValueError(f"알 수 없는 LLM 제공자: {self.provider} (가능: {', '.join(PROVIDERS)})")
        defaults = {"gemini": (settings.gemini_model, settings.embed_model),
                    "openai_compatible": (settings.llm_model, settings.llm_embed_model),
                    "rule": ("rule", f"hash-ngram-{HASH_DIM}")}[self.provider]
        self.model = model or defaults[0]
        self.embed_model = embed_model or defaults[1]
        self.base_url = (settings.llm_base_url or "").rstrip("/")
        self._http = http
        self._llm_key = settings.llm_api_key
        self.cache = cache or LLMCache(settings.llm_cache_db)
        cfg = load_config()
        self.max_retries = cfg["matcher"]["max_retries"]
        self.min_interval = 60.0 / cfg["llm"]["requests_per_minute"]
        self.rate_limit_retries = cfg["llm"]["rate_limit_retries"]
        self._last_call = 0.0
        self._sdk = sdk_client
        self._api_key = settings.gemini_api_key

    @property
    def sdk(self) -> Any:
        if self._sdk is None:
            if not self._api_key:
                raise LLMUnavailableError("GEMINI_API_KEY가 없고 캐시에도 없는 호출이다")
            from google import genai

            self._sdk = genai.Client(api_key=self._api_key)
        return self._sdk

    def _call(self, fn, **kwargs) -> Any:
        """무료 등급 분당 요청 제한을 지키고, 429·503·500이면 기다렸다 재시도한다."""
        for attempt in range(self.rate_limit_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                return fn(**kwargs)
            except Exception as e:
                code = getattr(e, "code", None)
                if code not in RETRYABLE_CODES or attempt == self.rate_limit_retries:
                    raise
                m = re.search(r"retry in ([\d.]+)s", str(e))
                # 429는 서버 안내 시간, 503·500(일시 과부하)은 점증 대기
                time.sleep(float(m.group(1)) + 1 if m else 15 * (attempt + 1))

    def _log(self, model: str, purpose: str, cache_hit: bool, in_tokens: int = 0, out_tokens: int = 0) -> None:
        conn = connect(self.db_mode)
        with conn:
            conn.execute(
                "INSERT INTO llm_calls (ts, model, in_tokens, out_tokens, purpose, cache_hit) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), model, in_tokens, out_tokens, purpose, int(cache_hit)),
            )
        conn.close()

    def generate(
        self,
        prompt: str,
        purpose: str,
        response_schema: type[T] | None = None,
        system: str | None = None,
    ) -> T | str:
        """텍스트 생성. `response_schema`를 주면 structured output으로 검증된 모델을 반환한다."""
        key = make_key(
            kind="generate",
            model=self.model,
            prompt=prompt,
            system=system,
            schema=response_schema.model_json_schema() if response_schema else None,
        )
        cached = self.cache.get(key)
        if cached is not None:
            self._log(self.model, purpose, cache_hit=True)
            return response_schema.model_validate_json(cached) if response_schema else cached
        if self.provider == "rule":
            raise LLMUnavailableError("rule 제공자: LLM 생성 없음 (호출부 규칙 판정 사용)")
        if self.provider == "openai_compatible":
            return self._oa_generate(key, prompt, purpose, response_schema, system)

        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=0,
            system_instruction=system,
            response_mime_type="application/json" if response_schema else None,
            response_schema=response_schema,
        )
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            resp = self._call(self.sdk.models.generate_content, model=self.model, contents=prompt, config=config)
            usage = getattr(resp, "usage_metadata", None)
            self._log(
                self.model,
                purpose,
                cache_hit=False,
                in_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                out_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            )
            text = resp.text or ""
            if response_schema is None:
                self.cache.set(key, "generate", self.model, text)
                return text
            try:
                parsed = response_schema.model_validate_json(text)
            except ValidationError as e:
                last_error = e
                continue
            self.cache.set(key, "generate", self.model, parsed.model_dump_json())
            return parsed
        raise LLMResponseError(f"{self.max_retries}회 재시도 후에도 스키마 검증 실패: {last_error}")

    def chat(self, contents: list[Any], purpose: str, tools: list[Any], system: str | None = None) -> Any:
        """함수 호출(function calling) 한 턴. 응답 Content를 반환하고, 대화 내용 해시로 캐시한다."""
        from google.genai import types

        if self.provider != "gemini":  # 함수 호출 미지원 → 빈 응답 (Orchestrator가 정해진 순서로 진행)
            return types.Content(role="model", parts=[])

        key = make_key(
            kind="chat",
            model=self.model,
            system=system,
            contents=[c.model_dump(mode="json", exclude_none=True) for c in contents],
            tools=[t.model_dump(mode="json", exclude_none=True) for t in tools],
        )
        cached = self.cache.get(key)
        if cached is not None:
            self._log(self.model, purpose, cache_hit=True)
            return types.Content.model_validate_json(cached)

        config = types.GenerateContentConfig(
            temperature=0,
            system_instruction=system,
            tools=tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self._call(self.sdk.models.generate_content, model=self.model, contents=contents, config=config)
        usage = getattr(resp, "usage_metadata", None)
        self._log(
            self.model,
            purpose,
            cache_hit=False,
            in_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            out_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )
        content = resp.candidates[0].content if resp.candidates else types.Content(role="model", parts=[])
        self.cache.set(key, "chat", self.model, content.model_dump_json(exclude_none=True))
        return content

    def embed(self, texts: list[str], purpose: str) -> list[list[float]]:
        """텍스트별로 캐시하고, 미스만 한 번에 API 호출한다."""
        if self.provider == "rule":  # 결정적 계산이라 캐시하지 않는다
            self._log(self.embed_model, purpose, cache_hit=False)
            return [hash_embedding(t) for t in texts]
        keys = [make_key(kind="embed", model=self.embed_model, text=t) for t in texts]
        results: list[list[float] | None] = []
        for k in keys:
            hit = self.cache.get(k)
            results.append(json.loads(hit) if hit is not None else None)

        miss_idx = [i for i, r in enumerate(results) if r is None]
        if len(miss_idx) < len(texts):
            self._log(self.embed_model, purpose, cache_hit=True)
        if miss_idx and self.provider != "gemini":
            vecs = self._oa_embed([texts[i] for i in miss_idx])
            self._log(self.embed_model, purpose, cache_hit=False)
            for i, v in zip(miss_idx, vecs):
                results[i] = v
                self.cache.set(keys[i], "embed", self.embed_model, json.dumps(v))
            return results  # type: ignore[return-value]
        if miss_idx:
            resp = self._call(self.sdk.models.embed_content, model=self.embed_model, contents=[texts[i] for i in miss_idx])
            # 임베딩 API는 출력 토큰이 없고 입력 토큰 수를 응답에 주지 않는다
            self._log(self.embed_model, purpose, cache_hit=False)
            for i, emb in zip(miss_idx, resp.embeddings):
                results[i] = list(emb.values)
                self.cache.set(keys[i], "embed", self.embed_model, json.dumps(results[i]))
        return results  # type: ignore[return-value]

    # ---------- OpenAI 호환 ----------

    @property
    def http(self) -> Any:
        if self._http is None:
            import httpx

            if not self.base_url or not self.model:
                raise LLMUnavailableError("openai_compatible: LLM_BASE_URL·LLM_MODEL이 필요하다")
            headers = {"Authorization": f"Bearer {self._llm_key}"} if self._llm_key else {}
            self._http = httpx.Client(base_url=self.base_url, headers=headers, timeout=120)
        return self._http

    def _oa_post(self, path: str, body: dict) -> dict:
        def send() -> dict:
            r = self.http.post(path, json=body)
            if r.status_code in RETRYABLE_CODES:
                err = RuntimeError(f"HTTP {r.status_code}")
                err.code = r.status_code  # type: ignore[attr-defined]
                raise err
            r.raise_for_status()
            return r.json()

        return self._call(send)

    def _oa_generate(self, key: str, prompt: str, purpose: str, schema: type[T] | None, system: str | None) -> T | str:
        sys_text = system or ""
        if schema is not None:
            sys_text += ("\n\n반드시 아래 JSON 스키마를 따르는 JSON 객체 하나만 출력한다.\n"
                         + json.dumps(schema.model_json_schema(), ensure_ascii=False))
        messages = ([{"role": "system", "content": sys_text}] if sys_text else []) + [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0}
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            data = self._oa_post("/chat/completions", body)
            usage = data.get("usage") or {}
            self._log(self.model, purpose, cache_hit=False,
                      in_tokens=usage.get("prompt_tokens", 0) or 0, out_tokens=usage.get("completion_tokens", 0) or 0)
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if schema is None:
                self.cache.set(key, "generate", self.model, text)
                return text
            try:
                parsed = schema.model_validate_json(_strip_fence(text))
            except ValidationError as e:
                last_error = e
                continue
            self.cache.set(key, "generate", self.model, parsed.model_dump_json())
            return parsed
        raise LLMResponseError(f"{self.max_retries}회 재시도 후에도 스키마 검증 실패: {last_error}")

    def _oa_embed(self, texts: list[str]) -> list[list[float]]:
        data = self._oa_post("/embeddings", {"model": self.embed_model, "input": texts})
        return [list(d["embedding"]) for d in sorted(data["data"], key=lambda d: d.get("index", 0))]


def _strip_fence(text: str) -> str:
    """```json ... ``` 감싸기를 벗긴다 (일부 호환 서버가 붙임)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return m.group(1) if m else text


def hash_embedding(text: str, dim: int = HASH_DIM) -> list[float]:
    """rule 제공자용 결정적 임베딩: 문자 2·3-gram 해시 버킷 빈도를 L2 정규화."""
    t = re.sub(r"\s+", " ", text.lower())
    v = [0.0] * dim
    for n in (2, 3):
        for i in range(len(t) - n + 1):
            h = int.from_bytes(hashlib.md5(t[i:i + n].encode()).digest()[:4], "little")
            v[h % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]
