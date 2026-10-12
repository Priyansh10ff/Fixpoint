"""Executes untrusted code in a short-lived, locked-down Docker container."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.types import LogConfig

from app.config import Settings
from app.sandbox.context import build_context, split_python_context
from app.sandbox.languages import LANGUAGES, LanguageSpec, detect_language
from app.schemas import RunResult

log = logging.getLogger("fixpoint.sandbox")

RUN_MARKER = "__FIXPOINT_RUN__"
COMPILE_FAILED_EXIT = 200
STARTUP_OVERHEAD_S = 3.0
HARNESS_DIR = Path(__file__).parent / "harness"


def build_script(spec: LanguageSpec, code: str) -> str:
    """Shell script executed inside the container.

    Compile output is only surfaced on failure (exit 200). A marker line on stdout separates the
    compile phase from the run phase so a timeout can be attributed to the right step.
    """
    compile_cmd, run_cmd = spec.commands(code)
    lines = []
    if compile_cmd:
        lines.append(
            f"{compile_cmd} > /tmp/.fp_compile 2>&1 || {{ cat /tmp/.fp_compile >&2; exit {COMPILE_FAILED_EXIT}; }}"
        )
    lines.append(f"echo {RUN_MARKER}")
    lines.append(f"exec {run_cmd} < /work/input.txt")
    return "\n".join(lines)


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

    async def run(self, code: str, language: str, stdin: str = "") -> RunResult:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_runs)
        async with self._semaphore:
            return await asyncio.to_thread(self.run_sync, code, language, stdin)

    def run_sync(self, code: str, language: str, stdin: str = "") -> RunResult:
        s = self.settings
        spec = LANGUAGES[language]
        hint = detect_language(code)
        base = {"language": language, "language_hint": hint if hint and hint != language else None}

        if len(code) > s.max_code_chars:
            return RunResult(status="sandbox_error", message=f"Code exceeds {s.max_code_chars} characters.", **base)
        if len(stdin) > s.max_stdin_chars:
            return RunResult(status="sandbox_error", message=f"Input exceeds {s.max_stdin_chars} characters.", **base)

        client = self.client()
        if client is None:
            return RunResult(
                status="sandbox_error",
                message="Docker is not reachable. Start Docker Desktop (or the Docker daemon) and try again.",
                **base,
            )

        image = s.image_for(language)
        budget = s.run_timeout_s + (s.compile_timeout_s if spec.compiled else 0) + STARTUP_OVERHEAD_S

        with tempfile.TemporaryDirectory(prefix="fixpoint-") as workdir:
            os.chmod(workdir, 0o755)  # container runs as nobody
            files = [(spec.filename(code), code), ("input.txt", stdin)]
            if spec.harness:
                harness_src = (HARNESS_DIR / spec.harness).read_text(encoding="utf-8")
                files.append((f".fixpoint_harness{spec.extension}", harness_src))
            for name, content in files:
                path = os.path.join(workdir, name)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
                os.chmod(path, 0o644)

            run_kwargs: dict[str, Any] = dict(
                image=image,
                command=["sh", "-c", build_script(spec, code)],
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
                return RunResult(
                    status="sandbox_error",
                    message=f"Image '{image}' is not available locally. Run: docker pull {shlex.quote(image)}",
                    **base,
                )
            except DockerException as exc:
                return RunResult(status="sandbox_error", message=f"Could not create container: {exc}", **base)

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
                return RunResult(status="sandbox_error", message=f"Sandbox failure: {exc}", **base)
            finally:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

        harness_ctx = None
        if spec.harness:
            text, harness_ctx = split_python_context(raw_err.decode("utf-8", errors="replace"))
            raw_err = text.encode("utf-8")
        stdout, t1 = _truncate(raw_out, s.max_output_bytes)
        stderr, t2 = _truncate(raw_err, s.max_output_bytes)
        reached_run = stdout.startswith(RUN_MARKER)
        if reached_run:
            stdout = stdout[len(RUN_MARKER) + 1 :]

        if timed_out:
            phase = "Compilation" if spec.compiled and not reached_run else "Execution"
            limit = s.compile_timeout_s if phase == "Compilation" else s.run_timeout_s
            status, message = "timeout", f"{phase} exceeded the time limit (~{limit:g}s)."
        elif oom:
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
            exit_code=None if timed_out else exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            truncated=t1 or t2,
            context=build_context(language, status, stderr, exit_code, harness_ctx, spec.entry_name(code)),
            **base,
        )
