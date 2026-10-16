"""Learn mode: hint ladder built after the loop finishes, and the explain endpoint."""

import asyncio

from app.agent.learn import learn_wrapper
from app.agent.loop import fix_loop
from app.llm.base import LLMError
from app.schemas import TestCase
from tests.fakes import ScriptedProvider, solver_sandbox

BUGGY = "a, b = map(int, input().split())\nprint(a - b)\n"
FIXED = BUGGY.replace("a - b", "a + b")
TESTS = [TestCase(input="2 3", expected="5")]
LADDER = {
    "concepts": ["operator choice"],
    "nudge": "What does line 2 compute for 2 and 3?",
    "concept": "Check that the arithmetic matches the problem statement.",
    "root_cause": "Line 2 subtracts instead of adding.",
    "fix_summary": "Use addition on line 2.",
}


def solve(code, stdin):
    a, b = map(int, stdin.split())
    return f"{a + b}\n" if "a + b" in code else f"{a - b}\n"


def run_learn(replies, solve_fn=solve, max_attempts=2):
    sandbox = solver_sandbox(solve_fn)
    provider = ScriptedProvider(replies)

    async def go():
        events = fix_loop(
            code=BUGGY,
            language="python",
            stdin="",
            provider=provider,
            model="m",
            sandbox=sandbox,
            tests=TESTS,
            max_attempts=max_attempts,
        )
        return [e async for e in learn_wrapper(events, original=BUGGY, language="python", provider=provider, model="m")]

    return asyncio.run(go()), provider


def test_hints_come_after_a_verified_fix_and_before_done():
    events, provider = run_learn([{"code": FIXED}, {"raw": LADDER}])
    names = [e[0] for e in events]
    assert names[-2:] == ["hints", "done"]
    assert events[0][1]["learn"] is True
    hints = events[-2][1]
    assert hints["status"] == "ok" and hints["based_on"] == "verified"
    assert hints["ladder"]["nudge"].startswith("What does line 2")
    # the hint prompt is built from the executed patch, not the first guess
    assert "+print(a + b)" in provider.prompts[-1]


def test_no_hints_when_unresolved():
    events, provider = run_learn([{"code": BUGGY.replace("a - b", "b - a")}, {"code": BUGGY.replace("a - b", "a * b")}])
    hints = dict(events)["hints"]
    assert hints["status"] == "unavailable"
    assert dict(events)["done"]["status"] == "unresolved"
    assert len(provider.prompts) == 2  # no extra call for hints


def test_hint_generation_failure_does_not_lose_the_fix():
    events, _ = run_learn([{"code": FIXED}, LLMError("model went away")])
    assert dict(events)["hints"]["status"] == "error"
    assert dict(events)["done"]["status"] == "verified"


def test_explain_endpoint():
    from tests.test_api import make_client

    provider = ScriptedProvider(
        [{"raw": {"summary": "Adds instead of subtracts.", "why": "Line 2 used `-`.", "concepts": ["arithmetic"]}}]
    )
    client, _ = make_client(provider=provider)
    r = client.post("/api/explain", json={"language": "python", "original": BUGGY, "patched": FIXED})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["explanation"]["summary"] == "Adds instead of subtracts."
    assert "+print(a + b)" in body["diff"]
    assert "1 | a, b = map" in provider.prompts[0]


def test_fix_endpoint_learn_mode_streams_hints():
    from tests.test_api import make_client, parse_sse

    sandbox = solver_sandbox(solve)
    provider = ScriptedProvider([{"code": FIXED}, {"raw": LADDER}])
    client, _ = make_client(sandbox, provider)
    payload = {"language": "python", "code": BUGGY, "mode": "learn", "tests": [{"input": "2 3", "expected": "5"}]}
    with client.stream("POST", "/api/fix", json=payload) as r:
        body = "".join(r.iter_text())
    names = [e[0] for e in parse_sse(body)]
    assert names[-2:] == ["hints", "done"]
