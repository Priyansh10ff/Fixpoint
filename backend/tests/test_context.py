from app.sandbox.context import build_context, split_python_context


def test_split_python_context_removes_marker_line():
    stderr = (
        'Traceback...\nIndexError: x\n\n__FIXPOINT_CTX__{"error_type": "IndexError", "line": 3, "locals": {"i": "7"}}\n'
    )
    clean, ctx = split_python_context(stderr)
    assert "__FIXPOINT_CTX__" not in clean
    assert clean.endswith("IndexError: x\n")
    assert ctx["line"] == 3


def test_python_context_from_harness():
    ctx = build_context(
        "python", "runtime_error", "", 1, {"error_type": "KeyError", "message": "'a'", "line": 4, "locals": {"d": "{}"}}
    )
    assert ctx.error_type == "KeyError" and ctx.line == 4 and ctx.locals == {"d": "{}"}


def test_no_context_for_ok():
    assert build_context("python", "ok", "", 0, None) is None


def test_timeout_and_oom():
    assert build_context("cpp", "timeout", "", None, None).error_type == "Time Limit Exceeded"
    assert build_context("java", "oom", "", 137, None).error_type == "Memory Limit Exceeded"


def test_javascript():
    stderr = (
        "/work/main.js:7\n    if (list[i].length > best.length) best = list[i]\n                ^\n\n"
        "TypeError: Cannot read properties of undefined (reading 'length')\n    at longest (/work/main.js:7:17)\n"
    )
    ctx = build_context("javascript", "runtime_error", stderr, 1, None)
    assert ctx.error_type == "TypeError" and ctx.line == 7 and "length" in ctx.message


def test_java_runtime_and_compile():
    stderr = (
        'Exception in thread "main" java.lang.StackOverflowError\n'
        "\tat Main.factorial(Main.java:5)\n\tat Main.factorial(Main.java:5)\n"
    )
    ctx = build_context("java", "runtime_error", stderr, 1, None, "Main")
    assert ctx.error_type == "StackOverflowError" and ctx.line == 5
    ctx = build_context("java", "compile_error", "/work/Main.java:3: error: ';' expected\n", 200, None, "Main")
    assert ctx.error_type == "Compilation error" and ctx.line == 3


def test_cpp_compile_asan_ubsan_signal():
    ctx = build_context("cpp", "compile_error", "/work/main.cpp:4:12: error: 'x' was not declared\n", 200, None)
    assert ctx.line == 4 and "not declared" in ctx.message
    asan = "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address\n    #0 0x5 in main /work/main.cpp:12\n"
    ctx = build_context("cpp", "runtime_error", asan, 1, None)
    assert ctx.error_type == "heap-buffer-overflow" and ctx.line == 12
    ub = "/work/main.cpp:3:9: runtime error: signed integer overflow: 2147483647 + 1\n"
    ctx = build_context("cpp", "runtime_error", ub, 1, None)
    assert ctx.error_type == "Undefined behavior" and ctx.line == 3
    assert build_context("cpp", "runtime_error", "", 139, None).error_type == "Segmentation fault"
