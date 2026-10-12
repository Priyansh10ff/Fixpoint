from app.agent.guards import changed_lines, check_patch, unified_diff

BASE = """def find(arr, x):
    lo, hi = 0, len(arr)
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == x:
            return mid
        lo = mid + 1
    return -1
"""


def test_accepts_small_real_fix():
    assert check_patch(BASE, BASE.replace("len(arr)", "len(arr) - 1"), "python").ok


def test_rejects_identical_and_empty():
    assert not check_patch(BASE, BASE + "\n\n", "python").ok
    assert not check_patch(BASE, "   ", "python").ok


def test_rejects_mass_deletion():
    r = check_patch(BASE, "def find(arr, x):\n    return -1\n", "python")
    assert not r.ok and "removes" in r.reason


def test_rejects_python_syntax_error():
    r = check_patch(BASE, BASE.replace("while lo <= hi:", "while lo <= hi"), "python")
    assert not r.ok and "not valid Python" in r.reason


def test_rejects_silencing_except():
    patched = BASE.replace(
        "        if arr[mid] == x:\n            return mid",
        "        try:\n            if arr[mid] == x:\n                return mid\n        except Exception:\n            pass",
    )
    r = check_patch(BASE, patched, "python")
    assert not r.ok and "silences" in r.reason


def test_allows_specific_except():
    patched = BASE.replace(
        "        if arr[mid] == x:\n            return mid",
        "        try:\n            if arr[mid] == x:\n                return mid\n        except IndexError:\n            break",
    )
    assert check_patch(BASE, patched, "python").ok


def test_rejects_empty_catch_in_js_java_cpp():
    js = "function f(a) {\n  const x = a.b\n  console.log(x)\n  return x\n}\nf(null)\n"
    js_bad = js.replace("  const x = a.b", "  let x\n  try { x = a.b } catch (e) {}")
    assert not check_patch(js, js_bad, "javascript").ok
    cpp = "int main(){\n int x=0;\n int y=1;\n int z=2;\n return y/x;\n}"
    cpp_bad = cpp.replace(" return y/x;", " try { return y/x; } catch (...) {}")
    assert not check_patch(cpp, cpp_bad, "cpp").ok


def test_diff_helpers():
    after = BASE.replace("len(arr)", "len(arr) - 1")
    d = unified_diff(BASE, after, "main.py")
    assert "-    lo, hi = 0, len(arr)" in d and "+    lo, hi = 0, len(arr) - 1" in d
    assert changed_lines(BASE, after) == 1
