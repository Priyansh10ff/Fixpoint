"""Scripted stand-ins for the sandbox and an LLM provider."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.llm.base import LLMError, LLMProvider, Message
from app.schemas import ErrorContext, RunResult


def ok(stdout: str = "", language: str = "python") -> RunResult:
    return RunResult(status="ok", exit_code=0, stdout=stdout, language=language)


def fail(
    error: str = "IndexError", line: int = 5, language: str = "python", status: str = "runtime_error"
) -> RunResult:
    return RunResult(
        status=status,
        exit_code=1,
        stderr=f"Traceback ...\n{error}: boom",
        language=language,
        context=ErrorContext(error_type=error, message="boom", line=line),
    )


class ScriptedSandbox:
    """Returns results from a function of the code, so tests describe behaviour, not call order."""

    def __init__(self, behaviour: Callable[[str], RunResult]):
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def run(self, code, language, stdin=""):
        self.calls.append(code)
        return self.behaviour(code)

    def client(self):
        return object()

    def image_status(self):
        return {"python": True, "javascript": True, "cpp": True, "java": True}

    last_error = None


class ScriptedProvider(LLMProvider):
    id = "fake"
    label = "Fake"

    def __init__(self, replies: list[dict | Exception]):
        super().__init__(default_model="fake-1")
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def list_models(self):
        return ["fake-1"]

    async def _complete(self, messages: list[Message], model, temperature, schema):
        self.prompts.append(messages[-1].content)
        if not self.replies:
            raise LLMError("no more scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(
            {
                "hypothesis": reply.get("hypothesis", "h"),
                "error_type": reply.get("error_type", "IndexError"),
                "root_cause": reply.get("root_cause", "rc"),
                "fix_summary": reply.get("fix_summary", "fs"),
                "fixed_code": reply["code"],
            }
        )
