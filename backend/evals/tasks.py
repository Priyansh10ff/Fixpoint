"""Benchmark task model, preparation (validation + visible/hidden split) and caching."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.sandbox.runner import Sandbox
from app.schemas import TestCase

DATA_DIR = Path(__file__).parent / "data"

MAX_VISIBLE_FAILING = 2
MAX_VISIBLE_PASSING = 1
MAX_HIDDEN = 10
MIN_CASES = 3


@dataclass
class Case:
    input: str
    expected: str

    def to_test(self, i: int) -> TestCase:
        return TestCase(id=f"c{i}", input=self.input, expected=self.expected)


@dataclass
class Task:
    """One buggy program. `reference` is the known-correct version, used only to validate the task."""

    id: str
    dataset: str
    language: str
    code: str
    reference: str
    cases: list[Case]
    category: str = ""
    visible: list[Case] = field(default_factory=list)
    hidden: list[Case] = field(default_factory=list)

    def visible_tests(self) -> list[TestCase]:
        return [c.to_test(i) for i, c in enumerate(self.visible)]

    def hidden_tests(self) -> list[TestCase]:
        return [c.to_test(i) for i, c in enumerate(self.hidden)]

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> Task:
        data = dict(data)
        for key in ("cases", "visible", "hidden"):
            data[key] = [Case(**c) for c in data.get(key, [])]
        return cls(**data)


@dataclass
class PrepareReport:
    kept: list[Task]
    dropped: list[tuple[str, str]]  # (task id, reason)


def fingerprint(tasks: list[Task]) -> str:
    h = hashlib.sha256()
    for t in tasks:
        h.update(json.dumps([t.id, t.language, t.code, t.reference, [asdict(c) for c in t.cases]]).encode())
    return h.hexdigest()[:16]


async def prepare(tasks: list[Task], sandbox: Sandbox, languages: set[str] | None = None) -> PrepareReport:
    """Validate each task and split its cases.

    A task is kept only if the reference passes every case and the buggy code fails at least one.
    Visible cases (shown to the agent) are up to 2 failing + 1 passing; the rest are held out as
    hidden cases, used only to check whether a "verified" fix is actually correct.
    """
    kept, dropped = [], []
    for task in tasks:
        if languages and task.language not in languages:
            dropped.append((task.id, f"{task.language} sandbox image not available"))
            continue
        tests = [c.to_test(i) for i, c in enumerate(task.cases)]
        ref = await sandbox.run_tests(task.reference, task.language, tests)
        if ref.status != "ok":
            dropped.append((task.id, f"invalid task: {ref.message or ref.status}"))
            continue
        if not ref.all_passed:
            # Cases even the known fix cannot pass here (time limit, float formatting) are unusable.
            usable = [task.cases[r.index] for r in ref.results if r.passed]
            if len(usable) < MIN_CASES:
                dropped.append((task.id, f"invalid task: reference passes only {ref.passed}/{ref.total} cases"))
                continue
            task.cases = usable
            tests = [c.to_test(i) for i, c in enumerate(task.cases)]
        bug = await sandbox.run_tests(task.code, task.language, tests)
        if bug.status == "sandbox_error":
            dropped.append((task.id, f"sandbox error: {bug.message}"))
            continue
        failing = [task.cases[r.index] for r in bug.results if not r.passed]
        passing = [task.cases[r.index] for r in bug.results if r.passed]
        if bug.status == "compile_error":
            failing = list(task.cases)
            passing = []
        if not failing:
            dropped.append((task.id, "buggy program passes every case"))
            continue
        visible = failing[:MAX_VISIBLE_FAILING] + passing[:MAX_VISIBLE_PASSING]
        rest = failing[MAX_VISIBLE_FAILING:] + passing[MAX_VISIBLE_PASSING:]
        task.visible, task.hidden = visible, rest[:MAX_HIDDEN]
        kept.append(task)
    return PrepareReport(kept, dropped)


def cache_path(dataset: str) -> Path:
    return DATA_DIR / f"{dataset}.prepared.json"


def save_prepared(dataset: str, source_fp: str, report: PrepareReport) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": dataset,
        "fingerprint": source_fp,
        "tasks": [t.to_json() for t in report.kept],
        "dropped": report.dropped,
    }
    cache_path(dataset).write_text(json.dumps(payload, indent=1), encoding="utf-8")


def load_prepared(dataset: str, source_fp: str) -> PrepareReport | None:
    path = cache_path(dataset)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("fingerprint") != source_fp:
        return None
    return PrepareReport([Task.from_json(t) for t in data["tasks"]], [tuple(d) for d in data["dropped"]])
