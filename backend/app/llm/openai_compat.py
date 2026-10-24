"""Adapter for OpenAI-compatible chat APIs: Ollama, Groq, OpenRouter."""

from __future__ import annotations

import json

import httpx

from app.llm.base import LLMError, LLMProvider, Message, record_usage


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        id: str,
        label: str,
        base_url: str,
        api_key: str = "",
        default_model: str = "",
        local: bool = False,
        requires_key: bool = True,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(default_model=default_model, timeout_s=timeout_s)
        self.id = id
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.local = local
        self.requires_key = requires_key
        self._transport = transport

    def configured(self) -> tuple[bool, str | None]:
        if self.requires_key and not self.api_key:
            return False, f"Set {self.id.upper()}_API_KEY in backend/.env"
        return True, None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    async def list_models(self) -> list[str]:
        try:
            async with self._client(5.0) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
                r.raise_for_status()
                data = r.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"{self.label} is not reachable at {self.base_url}: {exc}") from exc
        return sorted(m["id"] for m in data if isinstance(m, dict) and "id" in m)

    async def _complete(self, messages: list[Message], model: str, temperature: float, schema: dict) -> str:
        system = (
            "Respond with a single JSON object that matches this JSON schema. No prose, no code fences.\n"
            + json.dumps(schema)
        )
        payload = {
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }
        try:
            async with self._client(self.timeout_s) as client:
                r = await client.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.label} request failed: {exc}") from exc
        if r.status_code >= 400:
            raise LLMError(f"{self.label} returned HTTP {r.status_code}: {r.text[:300]}")
        try:
            body = r.json()
            usage = body.get("usage") or {}
            record_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected response from {self.label}: {r.text[:300]}") from exc
