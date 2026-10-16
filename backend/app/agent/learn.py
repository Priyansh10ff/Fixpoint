"""Learn mode: turn a fix that already passed the sandbox into graded hints, and explain patches.

Hints are generated only after the agent loop finishes, from the patch it produced, so they
point at a solution that was actually executed rather than at the model's first guess.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.agent.guards import unified_diff
from app.agent.loop import Event
from app.agent.prompts import _numbered
from app.llm.base import LLMError, LLMProvider, Message
from app.sandbox.languages import LANGUAGES
from app.schemas import Explanation, HintLadder

HINTABLE = {"verified", "fixed", "partial"}

HINT_PROMPT = """You are a patient programming tutor. A student's program has a bug. You are given the program, how it failed, and a patch that was executed in a sandbox and fixes it.

Write a hint ladder that lets the student find and fix the bug themselves. Each level reveals a bit more:
1. nudge: point to where to look, as a question. Do not name the bug or the fix.
2. concept: the general idea involved (e.g. inclusive vs exclusive bounds), not specific to this patch.
3. root_cause: what is wrong in this program and why it fails on the failing input.
4. fix_summary: the change to make, in words. No code blocks.

Rules: never include the corrected code. Keep each level to 1-3 sentences. Use the student's variable names and line numbers. Be precise, not chatty."""

EXPLAIN_PROMPT = """You explain code changes to a developer. Given the original program and a patched version (with a unified diff), explain what the patch changes and why it fixes the original. Reference line numbers of the original. Be precise and brief; do not restate the whole program."""


def _hint_input(language: str, original: str, final_code: str, done: dict[str, Any]) -> str:
    label = LANGUAGES[language].label
    filename = LANGUAGES[language].filename(original)
    diagnosis = done.get("diagnosis") or {}
    parts = [
        f"Language: {label}",
        f"Student's program, numbered:\n```\n{_numbered(original)}\n```",
        f"Patch that was executed and passed (status: {done['status']}):\n```diff\n{unified_diff(original, final_code, filename)}\n```",
    ]
    if diagnosis:
        parts.append(f"Debugger's diagnosis: {diagnosis.get('error_type', '')}. {diagnosis.get('root_cause', '')}")
    return "\n\n".join(parts)


async def learn_wrapper(
    events: AsyncIterator[Event],
    *,
    original: str,
    language: str,
    provider: LLMProvider,
    model: str,
    temperature: float = 0.2,
) -> AsyncIterator[Event]:
    """Pass the fix loop's events through; before `done`, emit a `hints` event built from the final patch."""
    async for name, data in events:
        if name == "start":
            data = {**data, "learn": True}
        if name != "done":
            yield name, data
            continue
        final_code = data.get("final_code")
        if data.get("status") in HINTABLE and final_code:
            try:
                ladder = await provider.complete_json(
                    [
                        Message("system", HINT_PROMPT),
                        Message("user", _hint_input(language, original, final_code, data)),
                    ],
                    HintLadder,
                    model=model,
                    temperature=temperature,
                )
                yield "hints", {"status": "ok", "based_on": data["status"], "ladder": ladder.model_dump()}
            except LLMError as exc:
                yield "hints", {"status": "error", "message": f"Could not generate hints: {exc}"}
        else:
            yield (
                "hints",
                {
                    "status": "unavailable",
                    "message": "No working patch was found, so there are no hints to build from it.",
                },
            )
        yield name, data


async def explain_patch(
    *, language: str, original: str, patched: str, provider: LLMProvider, model: str, temperature: float = 0.1
) -> tuple[Explanation, str]:
    filename = LANGUAGES[language].filename(original)
    diff = unified_diff(original, patched, filename)
    prompt = "\n\n".join(
        [
            f"Language: {LANGUAGES[language].label}",
            f"Original, numbered:\n```\n{_numbered(original)}\n```",
            f"Unified diff:\n```diff\n{diff or '(no changes)'}\n```",
        ]
    )
    explanation = await provider.complete_json(
        [Message("system", EXPLAIN_PROMPT), Message("user", prompt)], Explanation, model=model, temperature=temperature
    )
    return explanation, diff
