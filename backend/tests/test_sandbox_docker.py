"""Integration tests against a real Docker daemon.

Skipped automatically when Docker or the images are missing. Override images with
FIXPOINT_TEST_IMAGE_PYTHON / FIXPOINT_TEST_IMAGE_JAVASCRIPT to test against local builds.
"""

from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.sandbox.runner import Sandbox

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def sandbox():
    settings = Settings(
        _env_file=None,
        prepull_images=False,
        run_timeout_s=2,
        image_python=os.environ.get("FIXPOINT_TEST_IMAGE_PYTHON", "python:3.12-slim"),
        image_javascript=os.environ.get("FIXPOINT_TEST_IMAGE_JAVASCRIPT", "node:20-alpine"),
        max_output_bytes=4096,
    )
    sb = Sandbox(settings)
    if sb.client() is None:
        pytest.skip(f"Docker not reachable: {sb.last_error}")
    if not sb.image_status()["python"]:
        pytest.skip(f"Image {settings.image_python} not present")
    return sb


def run(sb, code, lang="python", stdin=""):
    return sb.run_sync(code, lang, stdin)


def test_ok_with_stdin(sandbox):
    r = run(sandbox, "a, b = map(int, input().split())\nprint(a + b)", stdin="2 3\n")
    assert r.status == "ok", r
    assert r.stdout == "5\n"
    assert r.exit_code == 0


def test_runtime_error_separates_streams(sandbox):
    r = run(sandbox, "print('before')\n[1][5]")
    assert r.status == "runtime_error"
    assert r.stdout == "before\n"
    assert "IndexError" in r.stderr


def test_timeout(sandbox):
    r = run(sandbox, "while True: pass")
    assert r.status == "timeout"
    assert r.exit_code is None


def test_no_network(sandbox):
    code = "import socket\ns=socket.socket(); s.settimeout(2)\ns.connect(('1.1.1.1', 80))"
    r = run(sandbox, code)
    assert r.status == "runtime_error"
    assert "OSError" in r.stderr or "unreachable" in r.stderr.lower()


def test_runs_as_nobody_with_readonly_code(sandbox):
    code = (
        "import os\nprint(os.getuid())\n"
        "try:\n    open('/work/x', 'w')\nexcept OSError as e:\n    print('ro', e.errno)\n"
        "open('/tmp/ok', 'w').write('1'); print('tmp ok')"
    )
    r = run(sandbox, code)
    assert r.status == "ok", r
    assert r.stdout.splitlines() == ["65534", "ro 30", "tmp ok"]


def test_fork_bomb_is_contained(sandbox):
    code = "import os\nwhile True:\n    try:\n        os.fork()\n    except OSError:\n        pass"
    r = run(sandbox, code)
    assert r.status in {"timeout", "runtime_error"}


def test_memory_limit(sandbox):
    r = run(sandbox, "x = bytearray(1024 * 1024 * 1024)\nprint(len(x))")
    assert r.status in {"oom", "runtime_error"}
    assert "1073741824" not in r.stdout


def test_output_is_truncated(sandbox):
    r = run(sandbox, "print('x' * 100000)")
    assert r.truncated
    assert "truncated" in r.stdout


def test_language_hint_does_not_override(sandbox):
    r = run(sandbox, "console.log('hi')", lang="python")
    assert r.language == "python"
    assert r.language_hint == "javascript"
    assert r.status == "runtime_error"


def test_javascript(sandbox):
    if not sandbox.image_status()["javascript"]:
        pytest.skip("node image not present")
    r = run(
        sandbox,
        "const l = require('fs').readFileSync(0, 'utf8').trim(); console.log(l.length)",
        lang="javascript",
        stdin="hello",
    )
    assert r.status == "ok", r
    assert r.stdout == "5\n"


def test_missing_image_message():
    settings = Settings(_env_file=None, prepull_images=False, image_python="fixpoint/does-not-exist:0")
    sb = Sandbox(settings)
    if sb.client() is None:
        pytest.skip("Docker not reachable")
    r = sb.run_sync("print(1)", "python")
    assert r.status == "sandbox_error"
    assert "docker pull fixpoint/does-not-exist:0" in r.message


def test_docker_down_message():
    def broken():
        raise RuntimeError("no daemon")

    sb = Sandbox(Settings(_env_file=None, prepull_images=False), client_factory=broken)
    r = sb.run_sync("print(1)", "python")
    assert r.status == "sandbox_error"
    assert "Docker is not reachable" in r.message


@pytest.fixture(scope="module")
def cpp_sandbox():
    settings = Settings(
        _env_file=None,
        prepull_images=False,
        run_timeout_s=2,
        image_cpp=os.environ.get("FIXPOINT_TEST_IMAGE_CPP", "gcc:14"),
    )
    sb = Sandbox(settings)
    if sb.client() is None or not sb.image_status()["cpp"]:
        pytest.skip("cpp image not present")
    return sb


def test_cpp_ok(cpp_sandbox):
    code = "#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a*b<<'\\n';}"
    r = cpp_sandbox.run_sync(code, "cpp", "6 7")
    assert r.status == "ok", r
    assert r.stdout == "42\n"


def test_cpp_compile_error(cpp_sandbox):
    r = cpp_sandbox.run_sync("int main(){ return x; }", "cpp")
    assert r.status == "compile_error"
    assert "'x' was not declared" in r.stderr
    assert r.stdout == ""


def test_cpp_asan_reports_out_of_bounds(cpp_sandbox):
    code = "#include <vector>\n#include <iostream>\nint main(){std::vector<int> v(3); int* p=v.data(); std::cout<<p[5];}"
    r = cpp_sandbox.run_sync(code, "cpp")
    assert r.status == "runtime_error"
    assert "AddressSanitizer" in r.stderr


def test_cpp_program_exiting_200_is_not_a_compile_error(cpp_sandbox):
    r = cpp_sandbox.run_sync("int main(){ return 200; }", "cpp")
    assert r.status == "runtime_error"


def test_cpp_run_timeout_is_attributed_to_execution(cpp_sandbox):
    r = cpp_sandbox.run_sync("int main(){ volatile int x=0; while(true){x++;} }", "cpp")
    assert r.status == "timeout"
    assert r.message.startswith("Execution")
