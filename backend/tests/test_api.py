from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMError, LLMProvider, Message
from app.llm.registry import ProviderRegistry
from app.main import create_app
from app.schemas import RunResult


class FakeSandbox:
    def __init__(self, result: RunResult | None = None):
        self.result = result
        self.calls = []

    async def run(self, code, language, stdin=""):
        self.calls.append((code, language, stdin))
        return self.result or RunResult(status="runtime_error", exit_code=1, stderr="IndexError", language=language)

    def client(self):
        return object()

    def image_status(self):
        return {"python": True, "javascript": False, "cpp": False, "java": False}

    last_error = None


class FakeProvider(LLMProvider):
    id = "fake"
    label = "Fake"

    def __init__(self, fixed_code="print(2)\n", fail=False):
        super().__init__(default_model="fake-1")
        self.fixed_code = fixed_code
        self.fail = fail
        self.prompts: list[list[Message]] = []

    async def list_models(self):
        return ["fake-1"]

    async def _complete(self, messages, model, temperature, schema):
        if self.fail:
            raise LLMError("provider down")
        self.prompts.append(messages)
        import json

        return json.dumps(
            {"error_type": "IndexError", "root_cause": "rc", "fix_summary": "fs", "fixed_code": self.fixed_code}
        )


def make_client(sandbox=None, provider=None):
    settings = Settings(_env_file=None, prepull_images=False)
    provider = provider or FakeProvider()
    app = create_app(settings, sandbox=sandbox or FakeSandbox(), registry=ProviderRegistry([provider], "fake"))
    return TestClient(app), provider


def test_run_passes_stdin_through():
    sandbox = FakeSandbox(RunResult(status="ok", exit_code=0, stdout="3\n", language="python"))
    client, _ = make_client(sandbox)
    r = client.post("/api/run", json={"language": "python", "code": "print(input())", "stdin": "3"})
    assert r.status_code == 200
    assert r.json()["stdout"] == "3\n"
    assert sandbox.calls == [("print(input())", "python", "3")]


def test_run_rejects_unknown_language_and_empty_code():
    client, _ = make_client()
    assert client.post("/api/run", json={"language": "ruby", "code": "x"}).status_code == 422
    assert client.post("/api/run", json={"language": "python", "code": ""}).status_code == 422


def test_debug_runs_code_server_side_and_returns_fix():
    sandbox = FakeSandbox()
    client, provider = make_client(sandbox)
    r = client.post("/api/debug", json={"language": "python", "code": "print(1)", "stdin": "5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True
    assert body["diagnosis"]["fixed_code"] == "print(2)\n"
    assert body["analysis"].startswith("**Error:** IndexError")
    assert body["model"] == "fake-1"
    assert sandbox.calls == [("print(1)", "python", "5")]
    user_prompt = provider.prompts[0][-1].content
    assert "1 | print(1)" in user_prompt and "IndexError" in user_prompt


def test_debug_reports_unchanged_code():
    client, _ = make_client(provider=FakeProvider(fixed_code="print(1)  \n"))
    body = client.post("/api/debug", json={"language": "python", "code": "print(1)"}).json()
    assert body["changed"] is False


def test_debug_returns_503_when_sandbox_unavailable():
    sandbox = FakeSandbox(RunResult(status="sandbox_error", message="Docker is not reachable.", language="python"))
    client, _ = make_client(sandbox)
    r = client.post("/api/debug", json={"language": "python", "code": "print(1)"})
    assert r.status_code == 503
    assert "Docker" in r.json()["detail"]


def test_debug_returns_502_on_llm_failure():
    client, _ = make_client(provider=FakeProvider(fail=True))
    r = client.post("/api/debug", json={"language": "python", "code": "print(1)"})
    assert r.status_code == 502
    assert "provider down" in r.json()["detail"]


def test_health_and_providers():
    client, _ = make_client()
    h = client.get("/api/health").json()
    assert h["docker"] is True and h["images"]["python"] is True
    p = client.get("/api/providers").json()
    assert p["default_provider"] == "fake"
    assert p["providers"][0]["models"] == ["fake-1"]


def test_cors_allows_configured_origin_only():
    client, _ = make_client()
    ok = client.options(
        "/api/run", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    )
    bad = client.options("/api/run", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        events.append((name, data))
    return events


def test_fix_streams_events():
    from tests.fakes import ScriptedProvider, ScriptedSandbox, fail, ok

    sandbox = ScriptedSandbox(lambda code: ok("3\n") if "fixed" in code else fail())
    provider = ScriptedProvider([{"code": "print(3)  # fixed\n"}])
    client, _ = make_client(sandbox, provider)
    with client.stream("POST", "/api/fix", json={"language": "python", "code": "print(x)"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = parse_sse(body)
    assert [e[0] for e in events] == ["start", "baseline", "attempt_start", "diagnosis", "patch", "verify", "done"]
    assert events[0][1]["model"] == "fake-1"
    assert events[-1][1]["status"] == "fixed"


def test_fix_rejects_unknown_provider_before_streaming():
    client, _ = make_client()
    r = client.post("/api/fix", json={"language": "python", "code": "print(1)", "provider": "nope"})
    assert r.status_code == 502


def test_fix_validates_max_attempts():
    client, _ = make_client()
    r = client.post("/api/fix", json={"language": "python", "code": "print(1)", "max_attempts": 50})
    assert r.status_code == 422
