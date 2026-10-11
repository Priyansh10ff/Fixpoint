"""Adapter for the Anthropic Messages API. Uses forced tool use for structured output."""

from __future__ import annotations

import json

import httpx

from app.llm.base import LLMError, LLMProvider, Message

API_VERSION = "2023-06-01"
TOOL_NAME = "submit_result"


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic"
    local = False

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        default_model: str = "",
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(default_model=default_model, timeout_s=timeout_s)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._transport = transport

    def configured(self) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "Set ANTHROPIC_API_KEY in backend/.env"
        return True, None

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers())
                r.raise_for_status()
                data = r.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"Anthropic is not reachable: {exc}") from exc
        return [m["id"] for m in data if isinstance(m, dict) and "id" in m]

    async def _complete(self, messages: list[Message], model: str, temperature: float, schema: dict) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        payload = {
            "model": model,
            "max_tokens": 8192,
            "temperature": temperature,
            "messages": convo,
            "tools": [{"name": TOOL_NAME, "description": "Submit the final answer.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }
        if system:
            payload["system"] = system
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as client:
                r = await client.post(f"{self.base_url}/messages", headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        if r.status_code >= 400:
            raise LLMError(f"Anthropic returned HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        for block in body.get("content", []):
            if block.get("type") == "tool_use":
                return json.dumps(block.get("input", {}))
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        return text
