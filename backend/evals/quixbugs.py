"""QuixBugs (Lin et al., 2017): 40 classic algorithms with one-line bugs. MIT licensed.

Fixpoint works on stdin programs, so each Python function is wrapped: the program reads its
arguments as JSON on stdin, calls the function, and prints the result as JSON. Programs whose tests
need graph objects (no JSON test file upstream) are not included.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from evals.tasks import DATA_DIR, Case, Task

RAW = "https://raw.githubusercontent.com/jkoppel/QuixBugs/master"
PROGRAMS = [
    "bitcount", "bucketsort", "find_first_in_sorted", "find_in_sorted", "flatten", "gcd", "get_factors",
    "hanoi", "is_valid_parenthesization", "kheapsort", "knapsack", "kth", "lcs_length", "levenshtein", "lis",
    "longest_common_subsequence", "max_sublist_sum", "mergesort", "next_palindrome", "next_permutation",
    "pascal", "possible_change", "powerset", "quicksort", "rpn_eval", "shunting_yard", "sieve", "sqrt",
    "subsequences", "to_base", "wrap",
]  # fmt: skip
CACHE = DATA_DIR / "quixbugs"

WRAPPER = """

if __name__ == "__main__":
    import json
    import sys
    import types

    _args = json.loads(sys.stdin.read())
    _result = {name}(*_args)
    if isinstance(_result, types.GeneratorType):
        _result = list(_result)
    print(json.dumps(_result))
"""


def _fetch(path: str) -> str:
    target = CACHE / path
    if target.exists():
        return target.read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{RAW}/{path}", timeout=30) as resp:  # noqa: S310 - fixed https URL
        text = resp.read().decode("utf-8")
    target.write_text(text, encoding="utf-8")
    return text


def _function_name(source: str, fallback: str) -> str:
    names = re.findall(r"^def (\w+)\(", source, re.M)
    return fallback if fallback in names else (names[0] if names else fallback)


def split_docstring(source: str) -> tuple[str, str]:
    """QuixBugs files are `code` followed by a top-level docstring describing the intended behaviour."""
    lines = source.splitlines()
    seen_def = False
    for i, line in enumerate(lines):
        if line.startswith("def "):
            seen_def = True
        elif seen_def and line.startswith('"""'):
            return "\n".join(lines[:i]).rstrip(), "\n".join(lines[i:]).strip()
    return source.rstrip(), ""


def reference_for(buggy: str, correct: str) -> str:
    """The upstream fixed files drop the docstring; reattach it so the reference differs only in code."""
    _, doc = split_docstring(buggy)
    code, _ = split_docstring(correct)
    return code + ("\n\n\n" + doc if doc else "") + "\n"


def wrap(source: str, name: str) -> str:
    return source.rstrip() + "\n" + WRAPPER.format(name=_function_name(source, name))


def parse_cases(text: str) -> list[Case]:
    cases = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        args, expected = json.loads(line)
        if not isinstance(args, list):
            args = [args]
        cases.append(Case(input=json.dumps(args), expected=json.dumps(expected)))
    return cases


def load(max_cases: int = 14) -> list[Task]:
    """Download (once) and build the tasks. Long test files are trimmed to keep runs fast."""
    tasks = []
    for name in PROGRAMS:
        buggy = _fetch(f"python_programs/{name}.py")
        correct = _fetch(f"correct_python_programs/{name}.py")
        cases = parse_cases(_fetch(f"json_testcases/{name}.json"))[:max_cases]
        tasks.append(
            Task(
                id=f"quixbugs/{name}",
                dataset="quixbugs",
                language="python",
                code=wrap(buggy, name),
                reference=wrap(reference_for(buggy, correct), name),
                cases=cases,
                category="algorithm",
            )
        )
    return tasks


def cached_files() -> list[Path]:
    return sorted(Path(CACHE).rglob("*")) if CACHE.exists() else []
