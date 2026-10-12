import asyncio

from app.agent.loop import fix_loop
from app.llm.base import LLMError
from tests.fakes import ScriptedProvider, ScriptedSandbox, fail, ok

BUGGY = "nums = [1, 2, 3]\ni = 3\nprint(nums[i])\nprint('done')\nprint('end')\n"
WRONG = BUGGY.replace("i = 3", "i = 4")  # still IndexError, same line
RIGHT = BUGGY.replace("i = 3", "i = 2")


def behaviour(code: str):
    if "i = 2" in code:
        return ok("3\ndone\nend\n")
    return fail("IndexError", line=3)


def collect(**kwargs):
    async def go():
        return [e async for e in fix_loop(**kwargs)]

    return asyncio.run(go())


def run_loop(replies, beh=behaviour, code=BUGGY, max_attempts=4):
    sandbox = ScriptedSandbox(beh)
    provider = ScriptedProvider(replies)
    events = collect(
        code=code,
        language="python",
        stdin="",
        provider=provider,
        model="fake-1",
        sandbox=sandbox,
        max_attempts=max_attempts,
    )
    return events, provider, sandbox


def names(events):
    return [e[0] for e in events]


def done(events):
    assert events[-1][0] == "done"
    return events[-1][1]


def test_fixes_on_first_attempt():
    events, _, sandbox = run_loop([{"code": RIGHT}])
    assert names(events) == ["start", "baseline", "attempt_start", "diagnosis", "patch", "verify", "done"]
    d = done(events)
    assert d["status"] == "fixed" and d["attempts"] == 1
    assert d["final_code"] == RIGHT
    assert "+i = 2" in d["diff"]
    assert sandbox.calls == [BUGGY, RIGHT]


def test_retries_with_history_and_fixes_on_second_attempt():
    events, provider, _ = run_loop([{"code": WRONG, "hypothesis": "index too big"}, {"code": RIGHT}])
    d = done(events)
    assert d["status"] == "fixed" and d["attempts"] == 2
    verify = [e[1] for e in events if e[0] == "verify"]
    assert [v["outcome"] for v in verify] == ["failed", "passed"]
    assert "Previous attempts" not in provider.prompts[0]
    assert "Attempt 1" in provider.prompts[1] and "index too big" in provider.prompts[1]
    assert "+i = 4" in provider.prompts[1]


def test_guard_rejection_counts_as_attempt_and_is_fed_back():
    silenced = BUGGY.replace("print(nums[i])", "try:\n    print(nums[i])\nexcept Exception:\n    pass")
    events, provider, sandbox = run_loop([{"code": silenced}, {"code": RIGHT}])
    assert "guard_reject" in names(events)
    assert done(events)["status"] == "fixed"
    assert silenced not in sandbox.calls  # rejected patches are never executed
    assert "rejected before running" in provider.prompts[1]


def test_unresolved_after_max_attempts():
    events, _, _ = run_loop([{"code": WRONG}, {"code": WRONG.replace("4", "5")}], max_attempts=2)
    d = done(events)
    assert d["status"] == "unresolved" and d["final_code"] is None and d["attempts"] == 2


def test_progress_then_partial():
    two_bugs = "a = [1]\nprint(a[1])\nprint(undefined_name)\n"
    first_fixed = two_bugs.replace("a[1]", "a[0]")

    def beh(code):
        if "a[1]" in code:
            return fail("IndexError", line=2)
        return fail("NameError", line=3)

    events, provider, _ = run_loop(
        [{"code": first_fixed}, {"code": first_fixed.replace("print(undefined_name)", "print(undefined_name )")}],
        beh=beh,
        code=two_bugs,
        max_attempts=2,
    )
    verify = [e[1]["outcome"] for e in events if e[0] == "verify"]
    assert verify[0] == "progress"
    d = done(events)
    assert d["status"] == "partial" and d["final_code"] == first_fixed
    # second prompt works from the partially fixed program, with a fresh history
    assert "a[0]" in provider.prompts[1] and "Previous attempts" not in provider.prompts[1]


def test_baseline_ok_and_model_finds_nothing():
    events, _, _ = run_loop([{"code": RIGHT, "error_type": "None"}], code=RIGHT)
    d = done(events)
    assert d["status"] == "no_bug"


def test_baseline_ok_with_suggestion_is_unverified():
    suggestion = RIGHT.replace("print('end')", "print('end!')")
    events, _, _ = run_loop([{"code": suggestion, "error_type": "Wrong Answer"}], code=RIGHT, beh=lambda c: ok())
    d = done(events)
    assert d["status"] == "unverified" and d["final_code"] == suggestion


def test_llm_error_ends_with_error():
    events, _, _ = run_loop([LLMError("model offline")])
    d = done(events)
    assert d["status"] == "error" and "model offline" in d["message"]


def test_sandbox_error_stops_before_llm():
    from app.schemas import RunResult

    events, provider, _ = run_loop(
        [], beh=lambda c: RunResult(status="sandbox_error", message="Docker down", language="python")
    )
    assert done(events)["status"] == "error"
    assert provider.prompts == []
