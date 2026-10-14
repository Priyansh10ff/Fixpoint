"""Executes untrusted code in a short-lived, locked-down Docker container."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.types import LogConfig

from app.config import Settings
from app.sandbox.context import build_context, split_python_context
from app.sandbox.languages import LANGUAGES, LanguageSpec, detect_language
from app.schemas import RunResult, TestCase, TestCaseResult, TestSuiteResult

log = logging.getLogger("fixpoint.sandbox")

RUN_MARKER = "__FIXPOINT_RUN__"
COMPILE_FAILED_EXIT = 200
STARTUP_OVERHEAD_S = 3.0
CASE_OVERHEAD_S = 0.5
TIMEOUT_EXIT = 124  # GNU/busybox `timeout`
KILLED_EXIT = 137
HARNESS_DIR = Path(__file__).parent / "harness"


def _compile_lines(spec: LanguageSpec, code: str) -> list[str]:
    compile_cmd, _ = spec.commands(code)
    if not compile_cmd:
        return []
    return [f"{compile_cmd} > /tmp/.fp_compile 2>&1 || {{ cat /tmp/.fp_compile >&2; exit {COMPILE_FAILED_EXIT}; }}"]


def build_script(spec: LanguageSpec, code: str) -> str:
    """Shell script for a single run with /work/input.txt as stdin.

    Compile output is only surfaced on failure (exit 200). A marker line on stdout separates the
    compile phase from the run phase so a timeout can be attributed to the right step.
    """
    _, run_cmd = spec.commands(code)
    return "\n".join([*_compile_lines(spec, code), f"echo {RUN_MARKER}", f"exec {run_cmd} < /work/input.txt"])


CASE_BEGIN = "__FP_BEGIN__"
CASE_END = "__FP_END__"
_CASE_OUT = re.compile(rf"{CASE_BEGIN} (\d+)\n(.*?)\n{CASE_END} \1 (\d+)\n", re.S)
_CASE_ERR = re.compile(rf"{CASE_BEGIN} (\d+)\n(.*?)\n{CASE_END} \1\n", re.S)


def build_test_script(spec: LanguageSpec, code: str, count: int, per_case_timeout: float) -> str:
    """Compile once, then run every case with its own `timeout`, framing each case's output with markers."""
    _, run_cmd = spec.commands(code)
    return "\n".join(
        [
            *_compile_lines(spec, code),
            f"echo {RUN_MARKER}",
            "i=0",
            f"while [ $i -lt {count} ]; do",
            f'  echo "{CASE_BEGIN} $i"; echo "{CASE_BEGIN} $i" >&2',
            f"  timeout {per_case_timeout:g} {run_cmd} < /work/tests/$i.in",
            "  rc=$?",
            f'  printf \'\\n{CASE_END} %s %s\\n\' "$i" "$rc"; printf \'\\n{CASE_END} %s\\n\' "$i" >&2',
            "  i=$((i+1))",
            "done",
        ]
    )


def normalise_output(text: str) -> str:
    """Compare outputs ignoring trailing spaces on each line and trailing blank lines."""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).rstrip("\n")


@dataclass
class RawExecution:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    timed_out: bool
    oom: bool
    duration_ms: int


def _truncate(raw: bytes, limit: int) -> tuple[str, bool]:
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace"), False
    text = raw[:limit].decode("utf-8", errors="replace")
    return text + f"\n… output truncated at {limit // 1024} KB", True


class Sandbox:
    def __init__(self, settings: Settings, client_factory: Callable[[], Any] = docker.from_env):
        self.settings = settings
        self._client_factory = client_factory
        self._client: Any | None = None
        self._client_lock = threading.Lock()
        self._semaphore: asyncio.Semaphore | None = None
        self.last_error: str | None = None

    # ---- docker connection -------------------------------------------------

    def client(self) -> Any | None:
        with self._client_lock:
            if self._client is not None:
                try:
                    self._client.ping()
                    return self._client
                except Exception:  # daemon went away
                    self._client = None
            try:
                client = self._client_factory()
                client.ping()
            except Exception as exc:  # DockerException, connection errors
                self.last_error = str(exc)
                return None
            self._client = client
            self.last_error = None
            return client

    def image_status(self) -> dict[str, bool]:
        client = self.client()
        status = {}
        for lang in LANGUAGES:
            image = self.settings.image_for(lang)
            if client is None:
                status[lang] = False
                continue
            try:
                client.images.get(image)
                status[lang] = True
            except (ImageNotFound, NotFound):
                status[lang] = False
            except DockerException:
                status[lang] = False
        return status

    def prepull_missing(self) -> None:
        """Pull images that are not present yet. Runs in a background thread on startup."""
        client = self.client()
        if client is None:
            log.warning("Docker not reachable, skipping image pre-pull: %s", self.last_error)
            return
        for lang, present in self.image_status().items():
            if present:
                continue
            image = self.settings.image_for(lang)
            log.info("Pulling %s for %s", image, lang)
            try:
                client.images.pull(image)
                log.info("Pulled %s", image)
            except DockerException as exc:
                log.warning("Could not pull %s: %s", image, exc)

    # ---- execution -----------------------------------------------------------

    def _limiter(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_runs)
        return self._semaphore

    async def run(self, code: str, language: str, stdin: str = "") -> RunResult:
        async with self._limiter():
            return await asyncio.to_thread(self.run_sync, code, language, stdin)

    async def run_tests(self, code: str, language: str, tests: list[TestCase]) -> TestSuiteResult:
        async with self._limiter():
            return await asyncio.to_thread(self.run_tests_sync, code, language, tests)

    def _execute(
        self, spec: LanguageSpec, code: str, script: str, extra_files: list[tuple[str, str]], budget: float
    ) -> RawExecution | str:
        """Run `script` in a fresh locked-down container. Returns raw output, or an error message."""
        s = self.settings
        client = self.client()
        if client is None:
            return "Docker is not reachable. Start Docker Desktop (or the Docker daemon) and try again."
        image = s.image_for(spec.id)

        with tempfile.TemporaryDirectory(prefix="fixpoint-") as workdir:
            os.chmod(workdir, 0o755)  # container runs as nobody
            files = [(spec.filename(code), code), *extra_files]
            if spec.harness:
                files.append((f".fixpoint_harness{spec.extension}", (HARNESS_DIR / spec.harness).read_text("utf-8")))
            for name, content in files:
                path = os.path.join(workdir, name)
                os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
                os.chmod(os.path.dirname(path), 0o755)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                os.chmod(path, 0o644)

            run_kwargs: dict[str, Any] = dict(
                image=image,
                command=["sh", "-c", script],
                user="65534:65534",
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": "rw,exec,nosuid,nodev,size=64m,mode=1777"},
                volumes={workdir: {"bind": "/work", "mode": "ro"}},
                working_dir="/tmp",
                environment={"HOME": "/tmp", "TMPDIR": "/tmp", **dict(spec.env)},
                mem_limit=f"{spec.mem_mb}m",
                memswap_limit=f"{spec.mem_mb}m",
                nano_cpus=int(s.cpu_limit * 1_000_000_000),
                pids_limit=spec.pids,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                # Caps what Docker stores for runaway output; we truncate further below.
                log_config=LogConfig(type="json-file", config={"max-size": "2m", "max-file": "1"}),
                detach=True,
            )
            if s.container_runtime:
                run_kwargs["runtime"] = s.container_runtime

            try:
                container = client.containers.create(**run_kwargs)
            except ImageNotFound:
                return f"Image '{image}' is not available locally. Run: docker pull {shlex.quote(image)}"
            except DockerException as exc:
                return f"Could not create container: {exc}"

            timed_out = False
            exit_code: int | None = None
            started = time.monotonic()
            try:
                container.start()
                try:
                    exit_code = container.wait(timeout=budget).get("StatusCode")
                except Exception:  # requests ReadTimeout / ConnectionError
                    timed_out = True
                    try:
                        container.kill()
                    except DockerException:
                        pass
                duration_ms = int((time.monotonic() - started) * 1000)
                raw_out = container.logs(stdout=True, stderr=False) or b""
                raw_err = container.logs(stdout=False, stderr=True) or b""
                oom = False
                try:
                    container.reload()
                    oom = bool(container.attrs.get("State", {}).get("OOMKilled"))
                except DockerException:
                    pass
            except DockerException as exc:
                return f"Sandbox failure: {exc}"
            finally:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass
        return RawExecution(raw_out, raw_err, exit_code, timed_out, oom, duration_ms)

    def _precheck(self, code: str) -> str | None:
        if len(code) > self.settings.max_code_chars:
            return f"Code exceeds {self.settings.max_code_chars} characters."
        return None

    def run_sync(self, code: str, language: str, stdin: str = "") -> RunResult:
        s = self.settings
        spec = LANGUAGES[language]
        hint = detect_language(code)
        base = {"language": language, "language_hint": hint if hint and hint != language else None}

        problem = self._precheck(code)
        if problem is None and len(stdin) > s.max_stdin_chars:
            problem = f"Input exceeds {s.max_stdin_chars} characters."
        if problem:
            return RunResult(status="sandbox_error", message=problem, **base)

        budget = s.run_timeout_s + (s.compile_timeout_s if spec.compiled else 0) + STARTUP_OVERHEAD_S
        raw = self._execute(spec, code, build_script(spec, code), [("input.txt", stdin)], budget)
        if isinstance(raw, str):
            return RunResult(status="sandbox_error", message=raw, **base)

        raw_err, harness_ctx = raw.stderr, None
        if spec.harness:
            text, harness_ctx = split_python_context(raw_err.decode("utf-8", errors="replace"))
            raw_err = text.encode("utf-8")
        stdout, t1 = _truncate(raw.stdout, s.max_output_bytes)
        stderr, t2 = _truncate(raw_err, s.max_output_bytes)
        reached_run = stdout.startswith(RUN_MARKER)
        if reached_run:
            stdout = stdout[len(RUN_MARKER) + 1 :]

        exit_code = raw.exit_code
        if raw.timed_out:
            phase = "Compilation" if spec.compiled and not reached_run else "Execution"
            limit = s.compile_timeout_s if phase == "Compilation" else s.run_timeout_s
            status, message = "timeout", f"{phase} exceeded the time limit (~{limit:g}s)."
        elif raw.oom:
            status, message = "oom", f"Memory limit exceeded ({spec.mem_mb} MB)."
        elif spec.compiled and not reached_run and exit_code == COMPILE_FAILED_EXIT:
            status, message = "compile_error", "Compilation failed."
        elif exit_code == 0:
            status, message = "ok", None
        else:
            status, message = "runtime_error", f"Process exited with code {exit_code}."

        return RunResult(
            status=status,
            message=message,
            exit_code=None if raw.timed_out else exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=raw.duration_ms,
            truncated=t1 or t2,
            context=build_context(language, status, stderr, exit_code, harness_ctx, spec.entry_name(code)),
            **base,
        )

    def run_tests_sync(self, code: str, language: str, tests: list[TestCase]) -> TestSuiteResult:
        """Run every test case against `code` in one container (one compile) and compare outputs."""
        s = self.settings
        spec = LANGUAGES[language]
        total = len(tests)

        def suite(status, message=None, results=(), duration_ms=0, compile_output=""):
            results = list(results)
            return TestSuiteResult(
                language=language,
                status=status,
                message=message,
                compile_output=compile_output,
                passed=sum(r.passed for r in results),
                total=total,
                duration_ms=duration_ms,
                results=results,
            )

        def blank(i: int, t: TestCase, verdict: str, stderr: str = "") -> TestCaseResult:
            return TestCaseResult(
                index=i,
                id=t.id,
                source=t.source,
                input=t.input,
                expected=t.expected,
                passed=False,
                verdict=verdict,
                stderr=stderr,
            )

        problem = self._precheck(code)
        if problem or not tests:
            return suite("sandbox_error", problem or "No test cases.")

        per_case = s.run_timeout_s
        budget = (
            (s.compile_timeout_s if spec.compiled else 0) + total * (per_case + CASE_OVERHEAD_S) + STARTUP_OVERHEAD_S
        )
        files = [(f"tests/{i}.in", t.input) for i, t in enumerate(tests)]
        raw = self._execute(spec, code, build_test_script(spec, code, total, per_case), files, budget)
        if isinstance(raw, str):
            return suite("sandbox_error", raw)

        out = raw.stdout.decode("utf-8", errors="replace")
        err = raw.stderr.decode("utf-8", errors="replace")
        reached_run = out.startswith(RUN_MARKER)
        if spec.compiled and not reached_run:
            if raw.timed_out:
                return suite(
                    "compile_error",
                    f"Compilation exceeded the time limit (~{s.compile_timeout_s:g}s).",
                    [blank(i, t, "compile_error") for i, t in enumerate(tests)],
                    raw.duration_ms,
                )
            compile_out, _ = _truncate(err.encode(), s.max_output_bytes)
            return suite(
                "compile_error",
                "Compilation failed.",
                [blank(i, t, "compile_error", compile_out) for i, t in enumerate(tests)],
                raw.duration_ms,
                compile_out,
            )

        outs = {int(m.group(1)): (m.group(2), int(m.group(3))) for m in _CASE_OUT.finditer(out)}
        errs = {int(m.group(1)): m.group(2) for m in _CASE_ERR.finditer(err)}
        limit = s.max_output_bytes
        results = []
        for i, t in enumerate(tests):
            if i not in outs:
                verdict = "timeout" if raw.timed_out else "oom" if raw.oom else "runtime_error"
                results.append(blank(i, t, verdict, "Case did not finish (sandbox limit reached)."))
                continue
            actual_raw, rc = outs[i]
            case_err = errs.get(i, "")
            harness_ctx = None
            if spec.harness:
                case_err, harness_ctx = split_python_context(case_err)
            actual, _ = _truncate(actual_raw.encode(), limit)
            case_err, _ = _truncate(case_err.encode(), limit)
            if rc == TIMEOUT_EXIT:
                verdict, status = "timeout", "timeout"
            elif rc == KILLED_EXIT:
                verdict, status = "oom", "oom"
            elif rc != 0:
                verdict, status = "runtime_error", "runtime_error"
            else:
                status = "ok"
                verdict = "passed" if normalise_output(actual_raw) == normalise_output(t.expected) else "wrong_answer"
            results.append(
                TestCaseResult(
                    index=i,
                    id=t.id,
                    source=t.source,
                    input=t.input,
                    expected=t.expected,
                    actual=actual,
                    stderr=case_err,
                    passed=verdict == "passed",
                    verdict=verdict,
                    exit_code=rc,
                    context=build_context(language, status, case_err, rc, harness_ctx, spec.entry_name(code)),
                )
            )
        return suite("ok", None, results, raw.duration_ms)
