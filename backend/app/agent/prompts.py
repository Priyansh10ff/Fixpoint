from __future__ import annotations

from dataclasses import dataclass

from app.sandbox.languages import LANGUAGES
from app.schemas import RunResult

MAX_LOG_CHARS = 6000
MAX_HISTORY_DIFF_CHARS = 2500

SYSTEM_PROMPT = """You are Fixpoint, a debugging engine. You receive a single-file program, the input it was run with, and the real output of running it in a sandbox.

Rules:
- Diagnose the actual failure shown in the output. Do not invent errors that are not supported by the code or the output.
- Start with a one-sentence hypothesis: the most likely cause, stated so a re-run can confirm or refute it.
- Name errors precisely (e.g. "IndexError", "NullPointerException", "Segmentation fault", "heap-buffer-overflow", "Wrong Answer", "Time Limit Exceeded").
- Explain the root cause technically and reference line numbers from the numbered listing.
- Fix the root cause with the smallest correct change. Never hide the error: do not delete the failing logic, wrap it in a blanket try/except or catch, or hardcode outputs.
- Keep the program's intended behaviour, structure, names and I/O format.
- Return the complete corrected file in the same language, without line numbers.
- If the program ran successfully and nothing indicates a bug, set error_type to "None", explain briefly, and return the code unchanged.
- If previous attempts are listed, they were executed and failed or were rejected. Do not repeat them; use what their results reveal."""


@dataclass
class AttemptRecord:
    n: int
    hypothesis: str
    diff: str
    outcome: str


def _numbered(code: str) -> str:
    lines = code.splitlines() or [""]
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))


def _clip(text: str, limit: int = MAX_LOG_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n… [clipped] …\n" + text[-half:]


def describe_run(run: RunResult) -> str:
    parts = [
        f"Sandbox result: status={run.status}, exit_code={run.exit_code}, duration={run.duration_ms}ms"
        + (f"\nNote: {run.message}" if run.message else ""),
    ]
    ctx = run.context
    if ctx:
        where = f" at line {ctx.line}" if ctx.line else ""
        func = f" in {ctx.function}()" if ctx.function and ctx.function != "<module>" else ""
        parts.append(f"Failure: {ctx.error_type}{where}{func}: {ctx.message}".rstrip(": "))
        if ctx.locals:
            rows = "\n".join(f"  {k} = {v}" for k, v in ctx.locals.items())
            parts.append(f"Local variables in the failing frame:\n{rows}")
    parts.append(f"stdout:\n```\n{_clip(run.stdout) or '(empty)'}\n```")
    parts.append(f"stderr:\n```\n{_clip(run.stderr) or '(empty)'}\n```")
    return "\n\n".join(parts)


def build_debug_prompt(
    code: str, language: str, stdin: str, run: RunResult, attempts: list[AttemptRecord] | None = None
) -> str:
    label = LANGUAGES[language].label
    parts = [
        f"Language: {label}",
        f"Program ({label}), numbered:\n```\n{_numbered(code)}\n```",
        f"Standard input:\n```\n{_clip(stdin) if stdin else '(empty)'}\n```",
        describe_run(run),
    ]
    if attempts:
        history = []
        for a in attempts:
            history.append(
                f"Attempt {a.n}\nHypothesis: {a.hypothesis or '(none given)'}\n"
                f"Patch (unified diff against the program above):\n```diff\n{_clip(a.diff, MAX_HISTORY_DIFF_CHARS) or '(no diff)'}\n```\n"
                f"Outcome: {a.outcome}"
            )
        parts.append("Previous attempts (all failed or were rejected):\n\n" + "\n\n".join(history))
    return "\n\n".join(parts)
