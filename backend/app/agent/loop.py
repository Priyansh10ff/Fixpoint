"""The Fixpoint agent loop: run → diagnose → guard → re-run → retry, streamed as events.

Each yielded item is (event_name, payload). The API layer turns these into Server-Sent Events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.agent.guards import changed_lines, check_patch, normalise, unified_diff
from app.agent.prompts import SYSTEM_PROMPT, AttemptRecord, build_debug_prompt
from app.llm.base import LLMError, LLMProvider, Message
from app.sandbox.languages import LANGUAGES
from app.sandbox.runner import Sandbox
from app.schemas import Diagnosis, RunResult

Event = tuple[str, dict[str, Any]]

DEFAULT_MAX_ATTEMPTS = 4
FAILING = {"runtime_error", "compile_error", "timeout", "oom"}


def _signature(run: RunResult) -> tuple:
    ctx = run.context
    return (run.status, ctx.error_type if ctx else None, ctx.line if ctx else None)


def _outcome_text(run: RunResult) -> str:
    ctx = run.context
    head = f"re-ran with status {run.status}"
    if ctx:
        head += (
            f": {ctx.error_type}"
            + (f" at line {ctx.line}" if ctx.line else "")
            + (f" ({ctx.message})" if ctx.message else "")
        )
    tail = (run.stderr or run.stdout).strip()[-600:]
    return head + (f"\nLast output:\n{tail}" if tail else "")


def _clean_code(code: str) -> str:
    return code.strip("\n") + "\n" if code.strip() else ""


@dataclass
class FixState:
    original: str
    base: str
    base_run: RunResult
    history: list[AttemptRecord] = field(default_factory=list)
    last_diagnosis: Diagnosis | None = None
    progressed: bool = False


async def fix_loop(
    *,
    code: str,
    language: str,
    stdin: str,
    provider: LLMProvider,
    model: str,
    sandbox: Sandbox,
    temperature: float = 0.1,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> AsyncIterator[Event]:
    filename = LANGUAGES[language].filename(code)
    yield "start", {"language": language, "provider": provider.id, "model": model, "max_attempts": max_attempts}

    baseline = await sandbox.run(code, language, stdin)
    yield "baseline", {"run": baseline.model_dump()}
    if baseline.status == "sandbox_error":
        yield "done", _done("error", message=baseline.message or "Sandbox error.", run=baseline)
        return

    async def diagnose(state: FixState) -> Diagnosis:
        prompt = build_debug_prompt(state.base, language, stdin, state.base_run, state.history)
        return await provider.complete_json(
            [Message("system", SYSTEM_PROMPT), Message("user", prompt)], Diagnosis, model=model, temperature=temperature
        )

    state = FixState(original=code, base=code, base_run=baseline)

    # Program already runs cleanly: without test cases there is nothing to verify against,
    # so ask once and report any change as an unverified suggestion.
    if baseline.status == "ok":
        yield "attempt_start", {"n": 1}
        try:
            d = await diagnose(state)
        except LLMError as exc:
            yield "done", _done("error", message=str(exc), run=baseline)
            return
        yield "diagnosis", {"n": 1, **_diag_payload(d)}
        patched = _clean_code(d.fixed_code)
        if (
            d.error_type.strip().lower() in {"none", "no bug", ""}
            or not patched
            or normalise(patched) == normalise(code)
        ):
            yield (
                "done",
                _done("no_bug", message="Runs without errors and the model found no bug.", diagnosis=d, run=baseline),
            )
            return
        guard = check_patch(code, patched, language)
        if not guard.ok:
            yield "guard_reject", {"n": 1, "reason": guard.reason}
            yield (
                "done",
                _done(
                    "no_bug",
                    message=f"Runs without errors. Suggested change rejected: {guard.reason}",
                    diagnosis=d,
                    run=baseline,
                ),
            )
            return
        yield "patch", _patch_payload(1, code, patched, filename)
        run = await sandbox.run(patched, language, stdin)
        yield "verify", {"n": 1, "run": run.model_dump(), "outcome": "passed" if run.status == "ok" else "failed"}
        if run.status != "ok":
            yield (
                "done",
                _done(
                    "no_bug",
                    message="Runs without errors. The suggested change broke it, so it was discarded.",
                    diagnosis=d,
                    run=baseline,
                ),
            )
            return
        yield (
            "done",
            _done(
                "unverified",
                message="The program already ran without errors. This change is a suggestion: add test cases (Phase 3) to verify it.",
                final_code=patched,
                original=code,
                filename=filename,
                diagnosis=d,
                run=run,
                attempts=1,
            ),
        )
        return

    for n in range(1, max_attempts + 1):
        yield "attempt_start", {"n": n}
        try:
            d = await diagnose(state)
        except LLMError as exc:
            yield "done", _done("error", message=str(exc), run=state.base_run, attempts=n - 1)
            return
        state.last_diagnosis = d
        yield "diagnosis", {"n": n, **_diag_payload(d)}

        patched = _clean_code(d.fixed_code)
        guard = check_patch(state.base, patched, language)
        if not guard.ok:
            yield "guard_reject", {"n": n, "reason": guard.reason}
            state.history.append(
                AttemptRecord(
                    n,
                    d.hypothesis,
                    unified_diff(state.base, patched, filename),
                    f"rejected before running: {guard.reason}",
                )
            )
            continue

        yield "patch", _patch_payload(n, state.base, patched, filename)
        run = await sandbox.run(patched, language, stdin)
        if run.status == "sandbox_error":
            yield "verify", {"n": n, "run": run.model_dump(), "outcome": "failed"}
            yield "done", _done("error", message=run.message or "Sandbox error.", run=run, attempts=n)
            return

        if run.status == "ok":
            yield "verify", {"n": n, "run": run.model_dump(), "outcome": "passed"}
            yield (
                "done",
                _done(
                    "fixed",
                    message=f"Patched program runs without errors after {n} attempt{'s' if n > 1 else ''}.",
                    final_code=patched,
                    original=code,
                    filename=filename,
                    diagnosis=d,
                    run=run,
                    attempts=n,
                ),
            )
            return

        # Failure moved somewhere else (different error or line) and the code still compiles:
        # keep the patch and continue from it, the original failure is gone.
        progressed = _signature(run) != _signature(state.base_run) and not (
            run.status == "compile_error" and state.base_run.status != "compile_error"
        )
        yield "verify", {"n": n, "run": run.model_dump(), "outcome": "progress" if progressed else "failed"}
        if progressed:
            state.base, state.base_run, state.history, state.progressed = patched, run, [], True
        else:
            state.history.append(
                AttemptRecord(n, d.hypothesis, unified_diff(state.base, patched, filename), _outcome_text(run))
            )

    if state.progressed:
        yield (
            "done",
            _done(
                "partial",
                message="The original error is fixed, but the program still fails. Review the partial fix or try a stronger model.",
                final_code=state.base,
                original=code,
                filename=filename,
                diagnosis=state.last_diagnosis,
                run=state.base_run,
                attempts=max_attempts,
            ),
        )
    else:
        yield (
            "done",
            _done(
                "unresolved",
                message=f"No patch passed after {max_attempts} attempts.",
                diagnosis=state.last_diagnosis,
                run=state.base_run,
                attempts=max_attempts,
            ),
        )


def _diag_payload(d: Diagnosis) -> dict[str, Any]:
    return {
        "hypothesis": d.hypothesis,
        "error_type": d.error_type,
        "root_cause": d.root_cause,
        "fix_summary": d.fix_summary,
    }


def _patch_payload(n: int, base: str, patched: str, filename: str) -> dict[str, Any]:
    return {
        "n": n,
        "code": patched,
        "diff": unified_diff(base, patched, filename),
        "changed_lines": changed_lines(base, patched),
    }


def _done(
    status: str,
    *,
    message: str,
    final_code: str | None = None,
    original: str | None = None,
    filename: str = "main",
    diagnosis: Diagnosis | None = None,
    run: RunResult | None = None,
    attempts: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "final_code": final_code,
        "diff": unified_diff(original, final_code, filename) if final_code and original else None,
        "diagnosis": diagnosis.model_dump() if diagnosis else None,
        "run": run.model_dump() if run else None,
        "attempts": attempts,
    }
