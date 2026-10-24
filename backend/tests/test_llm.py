import asyncio
import json

import httpx
import pytest

from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMError, Message, extract_json
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.registry import ProviderRegistry
from app.schemas import Diagnosis

GOOD = {"error_type": "IndexError", "root_cause": "r", "fix_summary": "f", "fixed_code": "print(1)\n"}


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(GOOD),
        "```json\n" + json.dumps(GOOD) + "\n```",
        "<think>let me see {not json}</think>\n" + json.dumps(GOOD),
        "Here you go: " + json.dumps(GOOD) + " hope it helps",
    ],
)
def test_extract_json(text):
    assert extract_json(text)["error_type"] == "IndexError"


def test_extract_json_raises_without_object():
    with pytest.raises(ValueError):
        extract_json("no json here")


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_openai_compat_parses_and_sends_auth():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return chat_response(json.dumps(GOOD))

    p = OpenAICompatProvider("groq", "Groq", "https://x/v1", "k", "m1", transport=httpx.MockTransport(handler))
    result = run(p.complete_json([Message("user", "hi")], Diagnosis))
    assert result.error_type == "IndexError"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m1"
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_openai_compat_repairs_once():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return chat_response("oops" if len(calls) == 1 else json.dumps(GOOD))

    p = OpenAICompatProvider(
        "ollama", "Ollama", "http://o/v1", default_model="m", requires_key=False, transport=httpx.MockTransport(handler)
    )
    assert run(p.complete_json([Message("user", "hi")], Diagnosis)).fixed_code == "print(1)\n"
    assert len(calls) == 2
    assert "not valid JSON" in calls[1]["messages"][-1]["content"]


def test_openai_compat_gives_up_after_repair():
    p = OpenAICompatProvider(
        "ollama",
        "Ollama",
        "http://o/v1",
        default_model="m",
        requires_key=False,
        transport=httpx.MockTransport(lambda r: chat_response("still bad")),
    )
    with pytest.raises(LLMError):
        run(p.complete_json([Message("user", "hi")], Diagnosis))


def test_openai_compat_http_error():
    p = OpenAICompatProvider(
        "groq",
        "Groq",
        "https://x/v1",
        "k",
        "m",
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key")),
    )
    with pytest.raises(LLMError, match="401"):
        run(p.complete_json([Message("user", "hi")], Diagnosis))


def test_openai_compat_picks_first_model_when_none_set():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
        assert json.loads(request.content)["model"] == "a"
        return chat_response(json.dumps(GOOD))

    p = OpenAICompatProvider(
        "ollama", "Ollama", "http://o/v1", requires_key=False, transport=httpx.MockTransport(handler)
    )
    run(p.complete_json([Message("user", "hi")], Diagnosis))


def test_anthropic_uses_forced_tool():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "submit_result", "input": GOOD}]})

    p = AnthropicProvider("key", default_model="claude-x", transport=httpx.MockTransport(handler))
    result = run(p.complete_json([Message("system", "sys"), Message("user", "hi")], Diagnosis))
    assert result.root_cause == "r"
    assert seen["headers"]["x-api-key"] == "key"
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "submit_result"}
    assert all(m["role"] != "system" for m in seen["body"]["messages"])


def test_registry_reports_unconfigured_providers():
    reg = ProviderRegistry(
        [
            OpenAICompatProvider(
                "ollama",
                "Ollama",
                "http://o/v1",
                requires_key=False,
                default_model="m",
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": "m"}]})),
            ),
            OpenAICompatProvider("groq", "Groq", "https://x/v1", api_key=""),
        ],
        default_provider="ollama",
    )
    info = {p.id: p for p in run(reg.describe())}
    assert info["ollama"].available and info["ollama"].models == ["m"]
    assert not info["groq"].available and "GROQ_API_KEY" in info["groq"].reason
    with pytest.raises(LLMError, match="not configured"):
        reg.get("groq")
    with pytest.raises(LLMError, match="Unknown provider"):
        reg.get("nope")


def test_usage_scope_counts_tokens_per_scope():
    from app.llm.base import usage_scope

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(GOOD)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    p = OpenAICompatProvider("groq", "Groq", "https://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    with usage_scope() as usage:
        run(p.complete_json([Message("user", "hi")], Diagnosis))
        run(p.complete_json([Message("user", "hi")], Diagnosis))
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (2, 200, 40)
    run(p.complete_json([Message("user", "hi")], Diagnosis))  # outside a scope: ignored
    assert usage.calls == 2
