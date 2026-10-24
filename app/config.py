"""환경 설정 로딩. 비밀키는 환경변수(.env) → st.secrets 순으로 조회한다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"

load_dotenv(ROOT_DIR / ".env")


def get_secret(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        # secrets.toml 없음 / streamlit 런타임 밖
        pass
    return default


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    embed_model: str
    learner_enabled: bool
    data_dir: Path
    llm_provider: str = "gemini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_embed_model: str | None = None

    @property
    def live_db(self) -> Path:
        return self.data_dir / "live.db"

    @property
    def sandbox_db(self) -> Path:
        return self.data_dir / "sandbox.db"

    @property
    def llm_cache_db(self) -> Path:
        return self.data_dir / "llm_cache.db"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"


def get_settings() -> Settings:
    """호출 시점의 환경을 읽는다 (테스트에서 env 교체 가능하도록 캐시하지 않음)."""
    data_dir = get_secret("ALPHA_DATA_DIR") or str(ROOT_DIR / "data")
    return Settings(
        gemini_api_key=get_secret("GEMINI_API_KEY"),
        gemini_model=get_secret("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        embed_model=get_secret("EMBED_MODEL", "gemini-embedding-001"),
        learner_enabled=_flag(get_secret("LEARNER_ENABLED", "false")),
        data_dir=Path(data_dir),
        # 제공자: env/secret LLM_PROVIDER가 config.yaml llm.provider보다 우선
        llm_provider=get_secret("LLM_PROVIDER") or load_config()["llm"].get("provider", "gemini"),
        llm_base_url=get_secret("LLM_BASE_URL") or load_config()["llm"].get("base_url"),
        llm_api_key=get_secret("LLM_API_KEY"),
        llm_model=get_secret("LLM_MODEL") or load_config()["llm"].get("model"),
        llm_embed_model=get_secret("LLM_EMBED_MODEL") or load_config()["llm"].get("embed_model"),
    )


@lru_cache(maxsize=1)
def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """config.yaml (임계치·가중치)."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
