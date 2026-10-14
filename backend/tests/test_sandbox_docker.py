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
    code = (
        "#include <vector>\n#include <iostream>\nint main(){std::vector<int> v(3); int* p=v.data(); std::cout<<p[5];}"
    )
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


def test_python_harness_captures_locals(sandbox):
    code = "def pick(items, k):\n    size = len(items)\n    return items[k]\n\nprint(pick([1, 2, 3], 7))\n"
    r = run(sandbox, code)
    assert r.status == "runtime_error"
    assert r.context.error_type == "IndexError"
    assert r.context.line == 3 and r.context.function == "pick"
    assert r.context.locals == {"items": "[1, 2, 3]", "k": "7", "size": "3"}
    # traceback looks like plain Python: no harness frames, no marker
    assert "fixpoint_harness" not in r.stderr and "runpy" not in r.stderr
    assert "__FIXPOINT_CTX__" not in r.stderr
    assert r.stderr.startswith("Traceback (most recent call last):")


def test_python_harness_syntax_error_and_exit_code(sandbox):
    r = run(sandbox, "x = (\n")
    assert r.context.error_type == "SyntaxError" and r.context.line == 1
    r = run(sandbox, "import sys\nprint('hi')\nsys.exit(3)")
    assert r.exit_code == 3 and r.stdout == "hi\n"


def test_python_harness_keeps_main_semantics(sandbox):
    code = "import sys\nif __name__ == '__main__':\n    print(sys.argv[0].endswith('main.py'), input())"
    r = run(sandbox, code, stdin="ok\n")
    assert r.status == "ok", r
    assert r.stdout == "True ok\n"


def test_run_tests_verdicts(sandbox):
    from app.schemas import TestCase as T

    code = "n = int(input())\nprint(sum(range(n)))\n"
    suite = sandbox.run_tests_sync(
        code, "python", [T(input="3", expected="3"), T(input="3", expected="6\n"), T(input="x", expected="0")]
    )
    assert suite.status == "ok" and suite.total == 3 and suite.passed == 1
    assert [r.verdict for r in suite.results] == ["passed", "wrong_answer", "runtime_error"]
    assert suite.results[1].actual == "3\n"
    assert suite.results[2].context.error_type == "ValueError"
    assert "__FP_" not in suite.results[2].stderr


def test_run_tests_per_case_timeout(sandbox):
    from app.schemas import TestCase as T

    suite = sandbox.run_tests_sync(
        "n = int(input())\nwhile n:\n    pass\nprint(n)",
        "python",
        [T(input="1", expected="1"), T(input="0", expected="0")],
    )
    assert [r.verdict for r in suite.results] == ["timeout", "passed"]


def test_run_tests_output_without_trailing_newline(sandbox):
    from app.schemas import TestCase as T

    suite = sandbox.run_tests_sync(
        "import sys\nsys.stdout.write(input()[::-1])", "python", [T(input="abc", expected="cba")]
    )
    assert suite.results[0].actual == "cba" and suite.results[0].passed


def test_run_tests_cpp_compiles_once(cpp_sandbox):
    from app.schemas import TestCase as T

    code = "#include <iostream>\nint main(){long long n;std::cin>>n;std::cout<<n*(n+1)/2<<'\\n';}"
    suite = cpp_sandbox.run_tests_sync(
        code, "cpp", [T(input=str(n), expected=str(n * (n + 1) // 2)) for n in (1, 10, 100000)]
    )
    assert suite.passed == 3
    bad = cpp_sandbox.run_tests_sync("int main(){ return x; }", "cpp", [T(input="1", expected="1")])
    assert bad.status == "compile_error" and "not declared" in bad.compile_output
