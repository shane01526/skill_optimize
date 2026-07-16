"""Provider 無關的 LLM 客戶端（同步）。

依環境變數自動選 provider（偵測順序）：
  - ANTHROPIC_API_KEY            → Anthropic Claude（預設，本機為 Claude 環境）
  - OPENAI_API_KEY               → OpenAI-compatible endpoint
  - GEMINI_API_KEY / GOOGLE_API_KEY → Google Gemini（google-genai SDK）
  - 皆無 / SKILL_REFINER_MOCK=1  → 內建 MockLLM（離線可跑，供打通流程 / 測試）

可用 SKILL_REFINER_PROVIDER 明確指定（anthropic / openai / gemini / mock）。

只暴露一個方法 ``chat(system, user, **kw) -> str``，回傳 assistant 文字。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

# 自動載入專案根目錄的 .env（若存在且裝了 python-dotenv）。
# 讓 API key 可持久設定且不進 git（.env 已被 .gitignore 排除）。
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(os.path.dirname(here), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)


_load_dotenv()

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_OPENAI_MODEL = "gpt-4o"
# 用 alias（永遠指向當前可用版本）；固定版號如 gemini-2.5-flash 對新用戶已停用。
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


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
            elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                provider = "gemini"
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
        elif provider == "gemini":
            self.model = model or os.environ.get("SKILL_REFINER_MODEL", DEFAULT_GEMINI_MODEL)
            self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
            self._base_url = base_url or os.environ.get("GEMINI_BASE_URL", "")
        else:  # mock
            self.model = model or "mock"

    # ---------------------------------------------------------------- #

    def chat(self, system: str, user: str, **kwargs: Any) -> str:
        """送出一次 chat，回傳 assistant 文字內容。

        真實 provider 遇暫時性錯誤（網路/DNS/rate-limit）會重試最多 3 次（指數退避），
        避免偶發網路失敗被誤記成 skill 失敗（pass_rate=0）。mock 不重試。
        """
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)

        if self.provider == "mock":
            return self._chat_mock(system, user)

        import time

        attempts = 3
        for i in range(attempts):
            try:
                if self.provider == "anthropic":
                    return self._chat_anthropic(system, user, temperature, max_tokens)
                if self.provider == "gemini":
                    return self._chat_gemini(system, user, temperature, max_tokens)
                return self._chat_openai(system, user, temperature, max_tokens)
            except Exception:  # noqa: BLE001
                if i == attempts - 1:
                    raise
                time.sleep(2 ** i)  # 1s, 2s 退避（不用 random，保持可重現）

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

    def _chat_gemini(self, system: str, user: str, temperature: float, max_tokens: int) -> str:
        from google import genai
        from google.genai import types

        client_kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            client_kwargs["http_options"] = types.HttpOptions(base_url=self._base_url)
        client = genai.Client(**client_kwargs)
        # Gemini 2.5 系列會先花 thinking token 才輸出；若把預算全花在思考，答案會被截斷
        # 甚至回空字串。對策：(1) 尊重傳入 max_tokens（下限 512），(2) 關閉 thinking budget，
        # 把 token 預算全留給答案。
        out_tokens = max(int(max_tokens), 512)
        cfg_kwargs: dict[str, Any] = {
            "system_instruction": system,
            "temperature": temperature,
            "max_output_tokens": out_tokens,
        }
        try:
            cfg_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:  # noqa: BLE001 - 舊版 SDK 無此欄位則略過
            pass
        resp = client.models.generate_content(
            model=self.model, contents=user, config=types.GenerateContentConfig(**cfg_kwargs)
        )
        # 偵測截斷（finish_reason == MAX_TOKENS）：記到 last_truncated 供上層/報告參考
        self.last_truncated = False
        try:
            fr = str(getattr(resp.candidates[0], "finish_reason", "") or "")
            if "MAX_TOKENS" in fr:
                self.last_truncated = True
        except Exception:  # noqa: BLE001
            pass
        return resp.text or ""

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
