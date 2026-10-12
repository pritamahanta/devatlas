"""Minimal LLM clients over plain HTTPS (httpx), so providers are swappable."""
from __future__ import annotations

from typing import Callable, Protocol

import httpx

from .config import settings

DEFAULT_MODELS = {"gemini": "gemini-3.8-flash", "anthropic": "claude-sonnet-5-5"}


class LLMError(RuntimeError):
    pass


class LLMNotConfigured(LLMError):
    pass


class LLM(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


class GeminiLLM:
    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def complete(self, system: str, user: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": settings.max_output_tokens},
        }
        # 2.5-flash "thinks" by default: thinking tokens count against maxOutputTokens and add
        # latency. This task is retrieval-grounded Q&A, so turn it off (budget 0 is only valid
        # for the flash family; 2.5-pro cannot disable thinking).
        if self.model.startswith("gemini-2.5-flash") and settings.gemini_thinking_budget >= 0:
            body["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": settings.gemini_thinking_budget}
        try:
            r = httpx.post(url, json=body, headers={"x-goog-api-key": self.api_key},
                           timeout=httpx.Timeout(settings.llm_timeout_s, connect=10.0))
        except httpx.HTTPError as e:
            raise LLMError(f"gemini request failed: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"gemini {r.status_code}: {r.text[:300]}")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMError(f"gemini returned no usable answer: {r.text[:300]}") from e
        if not text.strip():
            raise LLMError("gemini returned an empty answer")
        return text


class AnthropicLLM:
    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "max_tokens": settings.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        try:
            r = httpx.post("https://api.anthropic.com/v1/messages", json=body,
                           headers=headers, timeout=settings.llm_timeout_s)
        except httpx.HTTPError as e:
            raise LLMError(f"anthropic request failed: {e}") from e
        if r.status_code >= 400:
            raise LLMError(f"anthropic {r.status_code}: {r.text[:300]}")
        try:
            text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        except (KeyError, TypeError, ValueError) as e:
            raise LLMError(f"anthropic returned no usable answer: {r.text[:300]}") from e
        if not text.strip():
            raise LLMError("anthropic returned an empty answer")
        return text


class FakeLLM:
    """Scripted LLM for tests. `reply` is a string or a callable(system, user) -> str."""

    def __init__(self, reply: str | Callable[[str, str], str], model: str = "fake"):
        self.reply, self.model = reply, model
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply(system, user) if callable(self.reply) else self.reply


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        provider = settings.llm_provider.lower()
        model = settings.llm_model or DEFAULT_MODELS.get(provider, "")
        if provider == "gemini":
            if not settings.gemini_api_key:
                raise LLMNotConfigured("Set GEMINI_API_KEY in backend/.env")
            _llm = GeminiLLM(settings.gemini_api_key, model)
        elif provider == "anthropic":
            if not settings.anthropic_api_key:
                raise LLMNotConfigured("Set ANTHROPIC_API_KEY in backend/.env")
            _llm = AnthropicLLM(settings.anthropic_api_key, model)
        else:
            raise LLMNotConfigured(f"Unknown LLM_PROVIDER: {settings.llm_provider}")
    return _llm


def set_llm(llm: LLM | None) -> None:
    """Override (or reset with None) the process-wide LLM; used by tests."""
    global _llm
    _llm = llm
