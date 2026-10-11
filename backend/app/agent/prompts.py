from __future__ import annotations

from app.sandbox.languages import LANGUAGES
from app.schemas import RunResult

MAX_LOG_CHARS = 6000

SYSTEM_PROMPT = """You are Fixpoint, a debugging engine. You receive a single-file program, the input it was run with, and the real output of running it in a sandbox.

Rules:
- Diagnose the actual failure shown in the output. Do not invent errors that are not supported by the code or the output.
- Name errors precisely (e.g. "IndexError", "NullPointerException", "Segmentation fault", "heap-buffer-overflow", "Wrong Answer", "Time Limit Exceeded").
- Explain the root cause technically and reference line numbers from the numbered listing.
- Fix the root cause with the smallest correct change. Never hide the error: do not delete the failing logic, wrap it in a blanket try/except or catch, or hardcode outputs.
- Keep the program's intended behaviour, structure, names and I/O format.
- Return the complete corrected file in the same language, without line numbers.
- If the program ran successfully and nothing indicates a bug, set error_type to "None", explain briefly, and return the code unchanged."""


def _numbered(code: str) -> str:
    lines = code.splitlines() or [""]
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))


def _clip(text: str) -> str:
    if len(text) <= MAX_LOG_CHARS:
        return text
    half = MAX_LOG_CHARS // 2
    return text[:half] + "\n… [clipped] …\n" + text[-half:]


def build_debug_prompt(code: str, language: str, stdin: str, run: RunResult) -> str:
    label = LANGUAGES[language].label
    parts = [
        f"Language: {label}",
        f"Program ({label}), numbered:\n```\n{_numbered(code)}\n```",
        f"Standard input:\n```\n{_clip(stdin) if stdin else '(empty)'}\n```",
        f"Sandbox result: status={run.status}, exit_code={run.exit_code}, duration={run.duration_ms}ms"
        + (f"\nNote: {run.message}" if run.message else ""),
        f"stdout:\n```\n{_clip(run.stdout) or '(empty)'}\n```",
        f"stderr:\n```\n{_clip(run.stderr) or '(empty)'}\n```",
    ]
    return "\n\n".join(parts)
