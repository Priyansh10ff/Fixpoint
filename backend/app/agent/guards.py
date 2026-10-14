"""Cheap static checks that reject patches which hide a bug instead of fixing it."""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass

MAX_DELETION_RATIO = 0.4
MIN_LINES_FOR_DELETION_CHECK = 5

_PY_BROAD_EXCEPT = re.compile(r"^\s*except(\s+(Base)?Exception)?(\s+as\s+\w+)?\s*:\s*(pass|continue|\.\.\.)?\s*(#.*)?$")
_PY_SILENT_BODY = re.compile(r"^\s*(pass|continue|\.\.\.|return( None)?)\s*(#.*)?$")
_EMPTY_CATCH = {
    "javascript": re.compile(r"catch\s*(\([^)]*\))?\s*\{\s*\}"),
    "java": re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"),
    "cpp": re.compile(r"catch\s*\(\s*\.\.\.\s*\)\s*\{\s*\}"),
}


@dataclass
class GuardResult:
    ok: bool
    reason: str | None = None


def normalise(code: str) -> str:
    return "\n".join(line.rstrip() for line in code.strip().splitlines())


def _significant(code: str) -> list[str]:
    return [line.strip() for line in code.splitlines() if line.strip()]


def _python_silent_excepts(code: str) -> int:
    lines = code.splitlines()
    count = 0
    for i, line in enumerate(lines):
        if not _PY_BROAD_EXCEPT.match(line):
            continue
        if re.search(r":\s*(pass|continue|\.\.\.)\s*(#.*)?$", line):
            count += 1
            continue
        body = next((nxt for nxt in lines[i + 1 :] if nxt.strip()), "")
        if _PY_SILENT_BODY.match(body):
            count += 1
    return count


def _hardcoded(base: str, patched: str, expected_outputs: list[str]) -> str | None:
    """An expected output that newly appears as a string literal in the patch."""
    for expected in expected_outputs:
        value = expected.strip()
        if len(value) < 2:
            continue
        for quote in ('"', "'", "`"):
            literal = f"{quote}{value}{quote}"
            if literal in patched and literal not in base:
                return value
    return None


def check_patch(base: str, patched: str, language: str, expected_outputs: list[str] | None = None) -> GuardResult:
    if not patched.strip():
        return GuardResult(False, "The patch is empty.")
    if normalise(base) == normalise(patched):
        return GuardResult(False, "The patch is identical to the current code.")

    base_lines = _significant(base)
    if len(base_lines) >= MIN_LINES_FOR_DELETION_CHECK:
        matcher = difflib.SequenceMatcher(a=base_lines, b=_significant(patched), autojunk=False)
        kept = sum(block.size for block in matcher.get_matching_blocks())
        removed = (len(base_lines) - kept) / len(base_lines)
        if removed > MAX_DELETION_RATIO:
            return GuardResult(
                False, f"The patch removes {removed:.0%} of the original lines. Fix the bug without deleting the logic."
            )

    if expected_outputs:
        literal = _hardcoded(base, patched, expected_outputs)
        if literal is not None:
            short = literal if len(literal) <= 40 else literal[:37] + "..."
            return GuardResult(
                False, f"The patch hardcodes an expected test output ({short!r}). Fix the logic instead."
            )

    if language == "python":
        try:
            ast.parse(patched)
        except SyntaxError as exc:
            return GuardResult(False, f"The patch is not valid Python: {exc.msg} (line {exc.lineno}).")
        if _python_silent_excepts(patched) > _python_silent_excepts(base):
            return GuardResult(False, "The patch adds an except block that silences errors. Fix the cause instead.")
    elif language in _EMPTY_CATCH:
        pattern = _EMPTY_CATCH[language]
        if len(pattern.findall(patched)) > len(pattern.findall(base)):
            return GuardResult(
                False, "The patch adds an empty catch block that silences errors. Fix the cause instead."
            )

    return GuardResult(True)


def unified_diff(before: str, after: str, filename: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=2,
        )
    )


def changed_lines(before: str, after: str) -> int:
    matcher = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines(), autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")
