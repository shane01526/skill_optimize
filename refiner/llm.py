"""Provider 無關的 LLM 客戶端（同步）。

依環境變數自動選 provider：
  - ANTHROPIC_API_KEY  → Anthropic Claude（預設，本機為 Claude 環境）
  - OPENAI_API_KEY     → OpenAI-compatible endpoint
  - 皆無 / SKILL_REFINER_MOCK=1 → 內建 MockLLM（離線可跑，供打通流程 / 測試）

只暴露一個方法 ``chat(system, user, **kw) -> str``，回傳 assistant 文字。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OPENAI_MODEL = "gpt-4o"


class LLMClient:
    """統一介面。實際呼叫分派給 Anthropic / OpenAI / Mock。"""

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: str = "",
        base_url: str = "",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        mock_handler: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._mock_handler = mock_handler

        forced_mock = os.environ.get("SKILL_REFINER_MOCK", "").strip() in {"1", "true", "yes"}
        provider = (provider or os.environ.get("SKILL_REFINER_PROVIDER", "")).strip().lower()

        if mock_handler is not None or forced_mock or provider == "mock":
            self.provider = "mock"
            self.model = model or "mock"
            return

        if not provider:
            if os.environ.get("ANTHROPIC_API_KEY"):
                provider = "anthropic"
            elif os.environ.get("OPENAI_API_KEY"):
                provider = "openai"
            else:
                provider = "mock"

        self.provider = provider
        if provider == "anthropic":
            self.model = model or os.environ.get("SKILL_REFINER_MODEL", DEFAULT_ANTHROPIC_MODEL)
            self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            self._base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
        elif provider == "openai":
            self.model = model or os.environ.get("SKILL_REFINER_MODEL", DEFAULT_OPENAI_MODEL)
            self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            self._base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        else:  # mock
            self.model = model or "mock"

    # ---------------------------------------------------------------- #

    def chat(self, system: str, user: str, **kwargs: Any) -> str:
        """送出一次 chat，回傳 assistant 文字內容。"""
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)

        if self.provider == "mock":
            return self._chat_mock(system, user)
        if self.provider == "anthropic":
            return self._chat_anthropic(system, user, temperature, max_tokens)
        return self._chat_openai(system, user, temperature, max_tokens)

    # ---------------------------------------------------------------- #

    def _chat_mock(self, system: str, user: str) -> str:
        if self._mock_handler is not None:
            return self._mock_handler(system, user)
        from .mock_llm import default_mock_response

        return default_mock_response(system, user)

    def _chat_anthropic(self, system: str, user: str, temperature: float, max_tokens: int) -> str:
        from anthropic import Anthropic

        client_kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            client_kwargs["base_url"] = self._base_url
        client = Anthropic(**client_kwargs)
        resp = client.messages.create(
            model=self.model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
        )
        parts = [blk.text for blk in resp.content if getattr(blk, "type", "") == "text"]
        return "".join(parts)

    def _chat_openai(self, system: str, user: str, temperature: float, max_tokens: int) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""
