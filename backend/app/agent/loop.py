"""The Fixpoint agent loop: run → diagnose → guard → re-run → retry, streamed as events.

Two modes share one loop:
- run mode (no test cases): a patch passes when the program re-runs with status "ok".
- test mode: a patch passes when every user test case produces the expected output.

A pass becomes VERIFIED when there is evidence the patch fixes the observed bug:
user tests that failed before and pass now, or a generated regression case that fails on the
original program and passes on the patched one.

Each yielded item is (event_name, payload). The API layer turns these into Server-Sent Events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.agent.guards import changed_lines, check_patch, normalise, unified_diff
from app.agent.prompts import SYSTEM_PROMPT, AttemptRecord, build_debug_prompt, describe_tests
from app.llm.base import LLMError, LLMProvider, Message
from app.sandbox.languages import LANGUAGES
from app.sandbox.runner import Sandbox
from app.schemas import Diagnosis, ReproCase, RunResult, TestCase, TestSuiteResult

Event = tuple[str, dict[str, Any]]

DEFAULT_MAX_ATTEMPTS = 4


@dataclass
class Evaluation:
    """Outcome of running one version of the program."""

    run: RunResult | None = None
    tests: TestSuiteResult | None = None

    @property
    def sandbox_error(self) -> str | None:
        if self.tests is not None and self.tests.status == "sandbox_error":
            return self.tests.message or "Sandbox error."
        if self.run is not None and self.run.status == "sandbox_error":
            return self.run.message or "Sandbox error."
        return None

    @property
    def compile_error(self) -> bool:
        if self.tests is not None:
            return self.tests.status == "compile_error"
        return self.run is not None and self.run.status == "compile_error"

    @property
    def passed(self) -> bool:
        if self.tests is not None:
            return self.tests.all_passed
        return self.run is not None and self.run.status == "ok"

    @property
    def signature(self) -> tuple:
        if self.tests is not None:
            failing = tuple(
                (r.index, r.verdict, r.context.error_type if r.context else None)
                for r in self.tests.results
                if not r.passed
            )
            return (self.tests.status, self.tests.passed, failing)
        ctx = self.run.context if self.run else None
        return (self.run.status if self.run else None, ctx.error_type if ctx else None, ctx.line if ctx else None)

    def payload(self) -> dict[str, Any]:
        return {
            "run": self.run.model_dump() if self.run else None,
            "tests": self.tests.model_dump() if self.tests else None,
        }

    def outcome_text(self) -> str:
        if self.tests is not None:
            return "re-ran the tests: " + describe_tests(self.tests)
        run = self.run
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


def made_progress(new: Evaluation, base: Evaluation) -> bool:
    """The patch removed the original failure without breaking compilation."""
    if new.compile_error and not base.compile_error:
        return False
    if new.tests is not None and base.tests is not None:
        return new.tests.passed > base.tests.passed
    return new.signature != base.signature


def _clean_code(code: str) -> str:
    return code.strip("\n") + "\n" if code.strip() else ""


@dataclass
class FixState:
    base: str
    base_eval: Evaluation
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
    tests: list[TestCase] | None = None,
) -> AsyncIterator[Event]:
    tests = [t.model_copy(update={"source": "user"}) for t in (tests or [])]
    test_mode = bool(tests)
    expected_outputs = [t.expected for t in tests]
    filename = LANGUAGES[language].filename(code)

    async def evaluate(source: str) -> Evaluation:
        if test_mode:
            return Evaluation(tests=await sandbox.run_tests(source, language, tests))
        return Evaluation(run=await sandbox.run(source, language, stdin))

    async def diagnose(state: FixState) -> Diagnosis:
        prompt = build_debug_prompt(
            state.base, language, stdin, state.base_eval.run, state.history, tests=state.base_eval.tests
        )
        return await provider.complete_json(
            [Message("system", SYSTEM_PROMPT), Message("user", prompt)], Diagnosis, model=model, temperature=temperature
        )

    async def check_repro(n: int, repro: ReproCase | None, patched: str) -> dict[str, Any] | None:
        """A generated case counts only if the original fails it and the patch passes it."""
        if repro is None or (not repro.input.strip() and not repro.expected.strip()):
            return None
        case = TestCase(input=repro.input, expected=repro.expected, source="generated")
        before = await sandbox.run_tests(code, language, [case])
        after = await sandbox.run_tests(patched, language, [case])
        fails_original = before.status != "sandbox_error" and not before.all_passed
        passes_patched = after.all_passed
        if not fails_original:
            reason = "The original program already passes this case, so it does not reproduce the bug."
        elif not passes_patched:
            reason = "The patched program does not produce the expected output for this case."
        else:
            reason = None
        return {
            "n": n,
            "case": case.model_dump(),
            "original": before.results[0].model_dump() if before.results else None,
            "patched": after.results[0].model_dump() if after.results else None,
            "fails_original": fails_original,
            "passes_patched": passes_patched,
            "accepted": fails_original and passes_patched,
            "reason": reason,
        }

    yield (
        "start",
        {
            "language": language,
            "provider": provider.id,
            "model": model,
            "max_attempts": max_attempts,
            "mode": "tests" if test_mode else "run",
            "test_count": len(tests),
        },
    )

    baseline = await evaluate(code)
    yield "baseline", baseline.payload()
    if baseline.sandbox_error:
        yield "done", _done("error", message=baseline.sandbox_error, evaluation=baseline)
        return

    state = FixState(base=code, base_eval=baseline)

    if baseline.passed:
        if test_mode:
            yield "done", _done("no_bug", message=f"All {len(tests)} test cases pass.", evaluation=baseline)
            return
        async for event in _suggest_for_clean_run(code, language, filename, state, diagnose, evaluate):
            yield event
        return

    for n in range(1, max_attempts + 1):
        yield "attempt_start", {"n": n}
        try:
            d = await diagnose(state)
        except LLMError as exc:
            yield "done", _done("error", message=str(exc), evaluation=state.base_eval, attempts=n - 1)
            return
        state.last_diagnosis = d
        yield "diagnosis", {"n": n, **_diag_payload(d)}

        patched = _clean_code(d.fixed_code)
        guard = check_patch(state.base, patched, language, expected_outputs)
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
        result = await evaluate(patched)
        if result.sandbox_error:
            yield "verify", {"n": n, **result.payload(), "outcome": "failed"}
            yield "done", _done("error", message=result.sandbox_error, evaluation=result, attempts=n)
            return

        if result.passed:
            yield "verify", {"n": n, **result.payload(), "outcome": "passed"}
            repro = await check_repro(n, d.repro_case, patched)
            if repro is not None:
                yield "repro", repro
            accepted = repro is not None and repro["accepted"]
            evidence = []
            if test_mode:
                evidence.append(f"{len(tests)}/{len(tests)} test cases pass (at least one failed before)")
            if accepted:
                evidence.append("a generated regression case fails on the original and passes on the patch")
            verified = bool(evidence)
            attempts_text = f"{n} attempt{'s' if n > 1 else ''}"
            if verified:
                message = f"Verified after {attempts_text}: " + "; ".join(evidence) + "."
            else:
                why = repro["reason"] if repro else "No regression case was provided."
                message = f"The patched program runs without errors after {attempts_text}, but the fix is not verified. {why} Add test cases to verify the output."
            yield (
                "done",
                _done(
                    "verified" if verified else "fixed",
                    message=message,
                    final_code=patched,
                    original=code,
                    filename=filename,
                    diagnosis=d,
                    evaluation=result,
                    attempts=n,
                    repro=repro["case"] if accepted else None,
                ),
            )
            return

        progressed = made_progress(result, state.base_eval)
        yield "verify", {"n": n, **result.payload(), "outcome": "progress" if progressed else "failed"}
        if progressed:
            state.base, state.base_eval, state.history, state.progressed = patched, result, [], True
        else:
            state.history.append(
                AttemptRecord(n, d.hypothesis, unified_diff(state.base, patched, filename), result.outcome_text())
            )

    if state.progressed:
        yield (
            "done",
            _done(
                "partial",
                message="Part of the problem is fixed, but the program still fails. Review the partial fix or try a stronger model.",
                final_code=state.base,
                original=code,
                filename=filename,
                diagnosis=state.last_diagnosis,
                evaluation=state.base_eval,
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
                evaluation=state.base_eval,
                attempts=max_attempts,
            ),
        )


async def _suggest_for_clean_run(code, language, filename, state, diagnose, evaluate) -> AsyncIterator[Event]:
    """Program runs cleanly and there are no tests: ask once, report any change as unverified."""
    baseline = state.base_eval
    yield "attempt_start", {"n": 1}
    try:
        d = await diagnose(state)
    except LLMError as exc:
        yield "done", _done("error", message=str(exc), evaluation=baseline)
        return
    yield "diagnosis", {"n": 1, **_diag_payload(d)}
    patched = _clean_code(d.fixed_code)
    if d.error_type.strip().lower() in {"none", "no bug", ""} or not patched or normalise(patched) == normalise(code):
        yield (
            "done",
            _done(
                "no_bug",
                message="Runs without errors and the model found no bug. Add test cases to check the output.",
                diagnosis=d,
                evaluation=baseline,
            ),
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
                evaluation=baseline,
            ),
        )
        return
    yield "patch", _patch_payload(1, code, patched, filename)
    result = await evaluate(patched)
    yield "verify", {"n": 1, **result.payload(), "outcome": "passed" if result.passed else "failed"}
    if not result.passed:
        yield (
            "done",
            _done(
                "no_bug",
                message="Runs without errors. The suggested change broke it, so it was discarded.",
                diagnosis=d,
                evaluation=baseline,
            ),
        )
        return
    yield (
        "done",
        _done(
            "unverified",
            message="The program already ran without errors, so this change cannot be checked. Add test cases with the expected output to verify it.",
            final_code=patched,
            original=code,
            filename=filename,
            diagnosis=d,
            evaluation=result,
            attempts=1,
        ),
    )


def _diag_payload(d: Diagnosis) -> dict[str, Any]:
    return {
        "hypothesis": d.hypothesis,
        "error_type": d.error_type,
        "root_cause": d.root_cause,
        "fix_summary": d.fix_summary,
        "repro_case": d.repro_case.model_dump() if d.repro_case else None,
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
    evaluation: Evaluation | None = None,
    attempts: int = 0,
    repro: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "final_code": final_code,
        "diff": unified_diff(original, final_code, filename) if final_code and original else None,
        "diagnosis": diagnosis.model_dump() if diagnosis else None,
        **(evaluation.payload() if evaluation else {"run": None, "tests": None}),
        "attempts": attempts,
        "repro_case": repro,
    }
