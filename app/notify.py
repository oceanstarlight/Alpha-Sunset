"""텔레그램 알림 (원인-근거-결과 형식, 24시간 중복 방지)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app.config import get_secret, load_config

MAX_LEN = 3900  # 텔레그램 메시지 한도 4096자 여유


def format_message(title: str, chain: list[dict[str, str]], link: str | None = None) -> str:
    lines = [f"[Alpha Sunset] {title}"]
    for c in chain:
        lines += ["", f"■ {c['단계']} → {c['결과']}", f"  원인: {c['원인']}", f"  근거: {c['근거']}"]
    if link:
        lines += ["", f"리포트: {link}"]
    lines += ["", "※ 에이전트 제안이며 최종 결정은 사람이 한다."]
    text = "\n".join(lines)
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 20] + "\n…(리포트 참조)"


class Notifier:
    def __init__(self, state_path: Path, http: httpx.Client | None = None, now: datetime | None = None):
        self.state_path = state_path
        self._http = http or httpx.Client(timeout=20)
        self._now = now
        self.state: dict[str, str] = json.loads(state_path.read_text()) if state_path.exists() else {}

    @property
    def configured(self) -> bool:
        return bool(get_secret("TELEGRAM_BOT_TOKEN") and get_secret("TELEGRAM_CHAT_ID"))

    def _now_ts(self) -> datetime:
        return self._now or datetime.now().astimezone()

    def should_send(self, key: str) -> bool:
        last = self.state.get(key)
        hours = load_config()["korea"]["alerts"]["dedupe_hours"]
        return last is None or self._now_ts() - datetime.fromisoformat(last) >= timedelta(hours=hours)

    def send(self, key: str, text: str) -> str:
        """반환: sent | duplicate | not_configured | failed:<사유>."""
        if not self.should_send(key):
            return "duplicate"
        if not self.configured:
            return "not_configured"
        try:
            resp = self._http.post(f"https://api.telegram.org/bot{get_secret('TELEGRAM_BOT_TOKEN')}/sendMessage",
                                   json={"chat_id": get_secret("TELEGRAM_CHAT_ID"), "text": text,
                                         "disable_web_page_preview": True})
            resp.raise_for_status()
        except Exception as e:  # 토큰이 오류 메시지에 섞이지 않게 종류만 남긴다
            return f"failed:{type(e).__name__}"
        self.state[key] = self._now_ts().isoformat()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
        return "sent"
