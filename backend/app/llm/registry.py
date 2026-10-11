from __future__ import annotations

import asyncio
import time

from app.config import Settings
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMError, LLMProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.schemas import ProviderInfo

MODEL_CACHE_TTL_S = 60.0


class ProviderRegistry:
    def __init__(self, providers: list[LLMProvider], default_provider: str, default_model: str = ""):
        self.providers = {p.id: p for p in providers}
        self.default_provider = default_provider if default_provider in self.providers else providers[0].id
        self.default_model = default_model
        self._cache: dict[str, tuple[float, ProviderInfo]] = {}

    def get(self, provider_id: str | None) -> LLMProvider:
        pid = provider_id or self.default_provider
        provider = self.providers.get(pid)
        if provider is None:
            raise LLMError(f"Unknown provider '{pid}'.")
        ok, reason = provider.configured()
        if not ok:
            raise LLMError(f"{provider.label} is not configured. {reason}")
        return provider

    def model_for(self, provider: LLMProvider, model: str | None) -> str | None:
        if model:
            return model
        if provider.id == self.default_provider and self.default_model:
            return self.default_model
        return provider.default_model or None

    async def _info(self, provider: LLMProvider) -> ProviderInfo:
        cached = self._cache.get(provider.id)
        if cached and time.monotonic() - cached[0] < MODEL_CACHE_TTL_S:
            return cached[1]
        ok, reason = provider.configured()
        models: list[str] = []
        if ok:
            try:
                models = await provider.list_models()
            except LLMError as exc:
                ok, reason = False, str(exc)
        info = ProviderInfo(
            id=provider.id,
            label=provider.label,
            local=provider.local,
            available=ok,
            reason=reason,
            default_model=self.model_for(provider, None) or (models[0] if models else None),
            models=models,
        )
        self._cache[provider.id] = (time.monotonic(), info)
        return info

    async def describe(self) -> list[ProviderInfo]:
        return list(await asyncio.gather(*(self._info(p) for p in self.providers.values())))


def build_registry(s: Settings) -> ProviderRegistry:
    t = s.llm_timeout_s
    providers: list[LLMProvider] = [
        OpenAICompatProvider(
            "ollama",
            "Ollama",
            s.ollama_base_url,
            default_model=s.ollama_model,
            local=True,
            requires_key=False,
            timeout_s=t,
        ),
        OpenAICompatProvider("groq", "Groq", s.groq_base_url, s.groq_api_key, s.groq_model, timeout_s=t),
        OpenAICompatProvider(
            "openrouter", "OpenRouter", s.openrouter_base_url, s.openrouter_api_key, s.openrouter_model, timeout_s=t
        ),
        AnthropicProvider(s.anthropic_api_key, s.anthropic_base_url, s.anthropic_model, timeout_s=t),
    ]
    return ProviderRegistry(providers, s.default_provider, s.default_model)
