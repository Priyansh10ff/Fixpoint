from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)


@dataclass
class Usage:
    """Token counts for model calls made inside a `usage_scope()`."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


_usage: ContextVar[Usage | None] = ContextVar("fixpoint_llm_usage", default=None)


@contextmanager
def usage_scope() -> Iterator[Usage]:
    """Collect token usage for every model call in this context (per asyncio task)."""
    usage = Usage()
    token = _usage.set(usage)
    try:
        yield usage
    finally:
        _usage.reset(token)


def record_usage(input_tokens: int | None, output_tokens: int | None) -> None:
    usage = _usage.get()
    if usage is None:
        return
    usage.calls += 1
    usage.input_tokens += int(input_tokens or 0)
    usage.output_tokens += int(output_tokens or 0)


class LLMError(Exception):
    """Raised when a provider call fails or returns unusable output."""


@dataclass
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response (handles fences, <think> blocks, prose)."""
    text = _THINK.sub("", text).strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    for block in _FENCE.findall(text):
        try:
            value = json.loads(block.strip())
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("No JSON object found in model output.")


class LLMProvider(ABC):
    id: str
    label: str
    local: bool = False

    def __init__(self, default_model: str = "", timeout_s: float = 120.0):
        self.default_model = default_model
        self.timeout_s = timeout_s

    def configured(self) -> tuple[bool, str | None]:
        """Whether the provider has what it needs (e.g. an API key). Reachability is checked separately."""
        return True, None

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    @abstractmethod
    async def _complete(self, messages: list[Message], model: str, temperature: float, schema: dict) -> str:
        """Return raw model text that should contain a JSON object matching `schema`."""

    async def resolve_model(self, model: str | None) -> str:
        model = model or self.default_model
        if model:
            return model
        models = await self.list_models()
        if not models:
            raise LLMError(f"No model configured for {self.label}.")
        return models[0]

    async def complete_json(
        self, messages: list[Message], schema: type[T], model: str | None = None, temperature: float = 0.1
    ) -> T:
        model = await self.resolve_model(model)
        json_schema = schema.model_json_schema()
        history = list(messages)
        last_error = ""
        for _ in range(2):  # one repair retry
            text = await self._complete(history, model, temperature, json_schema)
            try:
                return schema.model_validate(extract_json(text))
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)
                history = history + [
                    Message("assistant", text),
                    Message(
                        "user",
                        "Your previous reply was not valid JSON for the required schema. "
                        f"Error: {last_error[:500]}\nReply again with only the JSON object.",
                    ),
                ]
        raise LLMError(f"{self.label} returned output that does not match the schema: {last_error[:300]}")
