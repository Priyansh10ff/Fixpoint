"""Turns raw sandbox output into a structured error context the agent and UI can use."""

from __future__ import annotations

import json
import re

from app.schemas import ErrorContext

CTX_MARKER = "__FIXPOINT_CTX__"

_JS_LINE = re.compile(r"/work/main\.js:(\d+)")
_JS_ERROR = re.compile(r"^(\w*(?:Error|Exception))(?: \[\w+\])?:? ?(.*)$", re.M)
_JAVA_EXC = re.compile(r'Exception in thread "\w+" ([\w.$]+)(?::\s*(.*))?')
_JAVA_LINE = re.compile(r"\((\w+)\.java:(\d+)\)")
_JAVA_COMPILE = re.compile(r"/work/\w+\.java:(\d+): error: (.*)")
_CPP_COMPILE = re.compile(r"/work/main\.cpp:(\d+):\d+: (?:fatal )?error: (.*)")
_CPP_ASAN = re.compile(r"ERROR: AddressSanitizer: ([\w-]+)")
_CPP_UBSAN = re.compile(r"/work/main\.cpp:(\d+):\d+: runtime error: (.*)")
_CPP_LINE = re.compile(r"/work/main\.cpp:(\d+)")
_SIGNALS = {139: "Segmentation fault", 136: "Floating point exception", 134: "Aborted", 137: "Killed"}


def split_python_context(stderr: str) -> tuple[str, dict | None]:
    """Remove the harness JSON line from stderr and return it parsed."""
    idx = stderr.rfind(CTX_MARKER)
    if idx == -1:
        return stderr, None
    end = stderr.find("\n", idx)
    raw = stderr[idx + len(CTX_MARKER) : end if end != -1 else None]
    clean = (stderr[:idx].rstrip("\n") + "\n" + (stderr[end + 1 :] if end != -1 else "")).rstrip("\n")
    clean = clean + "\n" if clean else ""
    try:
        return clean, json.loads(raw)
    except json.JSONDecodeError:
        return clean, None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def build_context(
    language: str, status: str, stderr: str, exit_code: int | None, harness: dict | None, entry: str = "Main"
) -> ErrorContext | None:
    if status == "ok" or status == "sandbox_error":
        return None
    if status == "timeout":
        return ErrorContext(error_type="Time Limit Exceeded", message="Program did not finish in time.")
    if status == "oom":
        return ErrorContext(error_type="Memory Limit Exceeded", message="Program used too much memory.")

    if language == "python" and harness:
        return ErrorContext(
            error_type=harness.get("error_type") or "Error",
            message=harness.get("message") or "",
            line=_int(harness.get("line")),
            function=harness.get("function"),
            locals=harness.get("locals") or {},
        )

    if language == "javascript":
        err = _JS_ERROR.search(stderr)
        line = _JS_LINE.search(stderr)
        if err or line:
            return ErrorContext(
                error_type=err.group(1) if err else "Error",
                message=(err.group(2) if err else "").strip(),
                line=_int(line.group(1)) if line else None,
            )

    if language == "java":
        if status == "compile_error":
            m = _JAVA_COMPILE.search(stderr)
            if m:
                return ErrorContext(error_type="Compilation error", message=m.group(2), line=_int(m.group(1)))
        exc = _JAVA_EXC.search(stderr)
        if exc:
            line = next((int(n) for f, n in _JAVA_LINE.findall(stderr) if f == entry), None)
            return ErrorContext(error_type=exc.group(1).split(".")[-1], message=(exc.group(2) or "").strip(), line=line)

    if language == "cpp":
        if status == "compile_error":
            m = _CPP_COMPILE.search(stderr)
            if m:
                return ErrorContext(error_type="Compilation error", message=m.group(2), line=_int(m.group(1)))
        ub = _CPP_UBSAN.search(stderr)
        if ub:
            return ErrorContext(error_type="Undefined behavior", message=ub.group(2), line=_int(ub.group(1)))
        asan = _CPP_ASAN.search(stderr)
        if asan:
            line = _CPP_LINE.search(stderr[asan.end() :])
            return ErrorContext(
                error_type=asan.group(1), message="AddressSanitizer report", line=_int(line.group(1)) if line else None
            )

    if exit_code in _SIGNALS:
        return ErrorContext(error_type=_SIGNALS[exit_code], message=f"Process exited with code {exit_code}.")
    if status == "compile_error":
        return ErrorContext(error_type="Compilation error", message="See compiler output.")
    return ErrorContext(error_type="Runtime error", message=f"Process exited with code {exit_code}.")
