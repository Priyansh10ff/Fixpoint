"""Eval harness: dataset adapters, task preparation, per-task runs and metrics (no network, no Docker)."""

import asyncio
import json

from evals import quixbugs
from evals.baselines import EchoProvider, OracleProvider
from evals.report import README_END, README_START, TaskRecord, summarize, table, update_readme
from evals.run import run_task
from evals.tasks import Case, Task, prepare
from tests.fakes import solver_sandbox

QB_BUGGY = '''def gcd(a, b):
    if b == 0:
        return a
    else:
        return gcd(a % b, b)


"""
Greatest Common Divisor
"""
'''
QB_CORRECT = """def gcd(a, b):
    if b == 0:
        return a
    else:
        return gcd(b, a % b)
"""


def test_quixbugs_reference_keeps_docstring_and_differs_only_in_code():
    ref = quixbugs.reference_for(QB_BUGGY, QB_CORRECT)
    assert '"""\nGreatest Common Divisor\n"""' in ref
    assert "gcd(b, a % b)" in ref and "gcd(a % b, b)" not in ref


def test_quixbugs_wrap_reads_json_args_and_prints_json():
    program = quixbugs.wrap(QB_CORRECT, "gcd")
    assert "_result = gcd(*_args)" in program
    assert "types.GeneratorType" in program


def test_quixbugs_parse_cases():
    cases = quixbugs.parse_cases('[[17, 0], 17]\n[[[1, 2], 3], [1, 2, 3]]\n["x", "y"]\n')
    assert cases[0] == Case(input="[17, 0]", expected="17")
    assert cases[1] == Case(input="[[1, 2], 3]", expected="[1, 2, 3]")
    assert cases[2].input == '["x"]'  # non-list args are wrapped


# A tiny "language" for the solver sandbox: program text "OUT=<expr>" where n is the input.
def solve(code, stdin):
    n = int(stdin)
    return str(eval(code.split("OUT=")[1], {"n": n})) + "\n"  # noqa: S307 - test-only


def make_task(code="OUT=n+1", reference="OUT=n*2", cases=None):
    cases = cases or [Case(str(i), str(i * 2)) for i in range(6)]
    return Task(id="t/double", dataset="t", language="python", code=code, reference=reference, cases=cases)


def test_prepare_splits_visible_failing_first_and_holds_out_the_rest():
    task = make_task()  # n+1 == 2n only for n=1
    report = asyncio.run(prepare([task], solver_sandbox(solve)))
    kept = report.kept[0]
    assert [c.input for c in kept.visible] == ["0", "2", "1"]  # 2 failing + 1 passing
    assert [c.input for c in kept.hidden] == ["3", "4", "5"]


def test_prepare_drops_tasks_the_bug_does_not_break_and_trims_cases_the_reference_fails():
    unbroken = make_task(code="OUT=n*2")
    flaky = make_task(reference="OUT=n*2 if n < 4 else 0")  # reference fails n=4,5 -> those cases dropped
    tiny = make_task(reference="OUT=0")  # passes only n=0 -> too few cases
    report = asyncio.run(prepare([unbroken, flaky, tiny], solver_sandbox(solve)))
    assert [t.id for t in report.kept] == ["t/double"]
    assert len(report.kept[0].cases) == 4
    reasons = [r for _, r in report.dropped]
    assert any("passes every case" in r for r in reasons)
    assert any("only 1/6" in r for r in reasons)


def test_prepare_skips_languages_without_an_image():
    report = asyncio.run(prepare([make_task()], solver_sandbox(solve), languages={"cpp"}))
    assert report.kept == [] and "image not available" in report.dropped[0][1]


def prepared(task):
    return asyncio.run(prepare([task], solver_sandbox(solve))).kept[0]


def test_run_task_with_oracle_is_verified_and_correct_on_hidden():
    task = prepared(make_task())
    record = asyncio.run(run_task(task, OracleProvider(), "oracle", solver_sandbox(solve), max_attempts=2))
    assert record.status == "verified"
    assert record.hidden_passed == record.hidden_total == 3
    assert record.correct and not record.false_verified
    assert record.llm_calls == 0  # baselines do not report tokens


def test_run_task_with_echo_is_unresolved():
    task = prepared(make_task())
    record = asyncio.run(run_task(task, EchoProvider(), "echo", solver_sandbox(solve), max_attempts=2))
    assert record.status == "unresolved" and not record.correct


def test_false_verified_is_measured_on_hidden_cases():
    # A patch that only fixes the visible cases (0, 1, 2) but not the hidden ones.
    task = prepared(make_task(reference="OUT=n*2"))
    task.reference = "OUT=n*2 if n < 3 else 0"
    record = asyncio.run(run_task(task, OracleProvider(), "oracle", solver_sandbox(solve), max_attempts=1))
    assert record.status == "verified" and record.false_verified


def rec(status, hidden_passed=3, hidden_total=3, attempts=1, latency=1.0, tokens=(100, 50)):
    return TaskRecord("t", "d", "python", "", status, attempts, latency, 1, tokens[0], tokens[1], 3, hidden_total,
                      hidden_passed, False)  # fmt: skip


def test_summarize_metrics():
    s = summarize([rec("verified"), rec("verified", hidden_passed=1), rec("unresolved", hidden_passed=0), rec("error")])
    assert s["tasks"] == 4
    assert s["verified_pct"] == 50.0
    assert s["correct_pct"] == 25.0
    assert s["false_verified_pct"] == 50.0  # 1 of 2 verified fails a hidden case
    assert s["errors"] == 1
    assert s["mean_tokens"] == 150


def test_table_and_readme_markers(tmp_path):
    run = {
        "meta": {"provider": "anthropic", "model": "m", "started_at": "2026-01-01T00:00:00Z", "baseline": False},
        "by_dataset": {"bench": summarize([rec("verified")])},
    }
    md = table([run])
    assert "| `m` · anthropic | bench | 1 | 100.0% |" in md
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{README_START}\nold\n{README_END}\noutro\n")
    assert update_readme(readme, [run])
    text = readme.read_text()
    assert "old" not in text and "`m` · anthropic" in text and text.endswith("outro\n")
    json.dumps(run)  # serialisable
