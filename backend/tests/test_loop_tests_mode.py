"""Agent loop with test cases: wrong answers, verification and the regression case."""

import asyncio

from app.agent.loop import fix_loop
from app.schemas import TestCase
from tests.fakes import ScriptedProvider, fail, ok, solver_sandbox

BUGGY = "a, b = map(int, input().split())\nprint(a - b)\n"
FIXED = BUGGY.replace("a - b", "a + b")
TESTS = [TestCase(input="2 3", expected="5"), TestCase(input="4 1", expected="5")]


def solve(code, stdin):
    a, b = map(int, stdin.split())
    return f"{a + b}\n" if "a + b" in code else f"{a - b}\n"


def run_loop(replies, solve_fn=solve, code=BUGGY, tests=TESTS, run_behaviour=None, max_attempts=4):
    sandbox = solver_sandbox(solve_fn, run_behaviour)
    provider = ScriptedProvider(replies)

    async def go():
        return [
            e
            async for e in fix_loop(
                code=code,
                language="python",
                stdin="",
                provider=provider,
                model="m",
                sandbox=sandbox,
                max_attempts=max_attempts,
                tests=tests,
            )
        ]

    return asyncio.run(go()), provider, sandbox


def done(events):
    assert events[-1][0] == "done"
    return events[-1][1]


def test_wrong_answer_is_fixed_and_verified_with_repro():
    events, provider, _ = run_loop(
        [{"code": FIXED, "error_type": "Wrong Answer", "repro": {"input": "1 1", "expected": "2"}}]
    )
    names = [e[0] for e in events]
    assert names == ["start", "baseline", "attempt_start", "diagnosis", "patch", "verify", "repro", "done"]
    assert events[0][1]["mode"] == "tests"
    assert events[1][1]["tests"]["passed"] == 0
    repro = dict(events)["repro"]
    assert repro["fails_original"] and repro["passes_patched"] and repro["accepted"]
    d = done(events)
    assert d["status"] == "verified"
    assert d["repro_case"] == {"id": None, "input": "1 1", "expected": "2", "source": "generated"}
    assert "2/2 test cases pass" in d["message"]
    # the prompt showed the failing case with expected vs actual
    assert "verdict=wrong_answer" in provider.prompts[0] and "expected output" in provider.prompts[0]


def test_verified_from_tests_even_when_repro_is_wrong():
    events, _, _ = run_loop([{"code": FIXED, "repro": {"input": "1 1", "expected": "3"}}])
    repro = dict(events)["repro"]
    assert repro["fails_original"] and not repro["passes_patched"] and not repro["accepted"]
    d = done(events)
    assert d["status"] == "verified" and d["repro_case"] is None


def test_all_tests_pass_means_no_bug_without_model_call():
    events, provider, _ = run_loop([], code=FIXED)
    assert done(events)["status"] == "no_bug"
    assert provider.prompts == []


def test_hardcoded_expected_output_is_rejected():
    tests = [TestCase(input="2 3", expected="five"), TestCase(input="4 1", expected="five")]
    cheat = BUGGY.replace("print(a - b)", "print('five')")

    def word_solve(code, stdin):
        return "five\n" if "'five'" in code else solve(code, stdin)

    events, _, sandbox = run_loop([{"code": cheat}, {"code": cheat}], solve_fn=word_solve, tests=tests, max_attempts=2)
    rejects = [e[1] for e in events if e[0] == "guard_reject"]
    assert len(rejects) == 2 and "hardcodes" in rejects[0]["reason"]
    assert all(cheat not in call[0] for call in sandbox.test_calls)
    assert done(events)["status"] == "unresolved"


def test_more_passing_cases_counts_as_progress():
    tests = [
        TestCase(input="2 3", expected="5"),
        TestCase(input="0 0", expected="0"),
        TestCase(input="1 2", expected="3"),
    ]
    half = BUGGY.replace("a - b", "abs(a - b)")  # fixes nothing for these... use a solver keyed on markers

    def staged(code, stdin):
        a, b = map(int, stdin.split())
        if "a + b" in code:
            return f"{a + b}\n"
        if "abs" in code:
            return "5\n" if stdin == "2 3" else f"{a - b}\n"
        return f"{a - b}\n"

    events, provider, _ = run_loop([{"code": half}, {"code": FIXED}], solve_fn=staged, tests=tests)
    outcomes = [e[1]["outcome"] for e in events if e[0] == "verify"]
    assert outcomes == ["progress", "passed"]
    assert done(events)["status"] == "verified"
    assert "abs(a - b)" in provider.prompts[1]  # continued from the partial patch


def test_crash_fix_without_tests_verified_by_repro():
    code = "nums = [1, 2, 3]\ni = int(input())\nprint(nums[i])\n"
    fixed = code.replace("print(nums[i])", "print(nums[min(i, len(nums) - 1)])")

    def solve_crash(src, stdin):
        i = int(stdin)
        nums = [1, 2, 3]
        if "min(" in src:
            return f"{nums[min(i, 2)]}\n"
        return f"{nums[i]}\n"

    events, _, _ = run_loop(
        [{"code": fixed, "repro": {"input": "5", "expected": "3"}}],
        solve_fn=solve_crash,
        code=code,
        tests=[],
        run_behaviour=lambda src: ok("3\n") if "min(" in src else fail("IndexError", line=3),
    )
    assert events[0][1]["mode"] == "run"
    d = done(events)
    assert d["status"] == "verified" and "regression case" in d["message"]


def test_crash_fix_without_repro_is_fixed_not_verified():
    code = "nums = [1, 2, 3]\nprint(nums[3])\n"
    fixed = code.replace("nums[3]", "nums[2]")
    events, _, _ = run_loop(
        [{"code": fixed}],
        code=code,
        tests=[],
        run_behaviour=lambda src: ok("3\n") if "nums[2]" in src else fail("IndexError", line=2),
    )
    d = done(events)
    assert d["status"] == "fixed" and "not verified" in d["message"]
