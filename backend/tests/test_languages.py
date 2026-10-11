from app.sandbox.languages import LANGUAGES, detect_language
from app.sandbox.runner import COMPILE_FAILED_EXIT, RUN_MARKER, build_script

JAVA = LANGUAGES["java"]


def test_java_filename_matches_public_class():
    code = "public class Solution {\n public static void main(String[] a) {}\n}"
    assert JAVA.filename(code) == "Solution.java"
    compile_cmd, run_cmd = JAVA.commands(code)
    assert compile_cmd.endswith("/work/Solution.java")
    assert run_cmd.endswith(" Solution")


def test_java_without_public_class_uses_class_with_main():
    code = "class Helper {}\nclass App {\n static void main(String[] a) {}\n}"
    assert JAVA.entry_name(code) == "App"


def test_java_defaults_to_main():
    assert JAVA.entry_name("// nothing here") == "Main"


def test_non_java_uses_main():
    assert LANGUAGES["python"].filename("public class X {}") == "main.py"
    assert LANGUAGES["cpp"].filename("int main(){}") == "main.cpp"


def test_script_for_interpreted_language_has_no_compile_step():
    script = build_script(LANGUAGES["python"], "print(1)")
    assert "exit 200" not in script
    assert script.splitlines()[0] == f"echo {RUN_MARKER}"
    assert script.endswith("< /work/input.txt")


def test_script_for_compiled_language_compiles_into_tmp():
    script = build_script(LANGUAGES["cpp"], "int main(){}")
    first = script.splitlines()[0]
    assert "-o /tmp/app /work/main.cpp" in first
    assert f"exit {COMPILE_FAILED_EXIT}" in first


def test_detect_language():
    assert detect_language("def f(x):\n    return x") == "python"
    assert detect_language("console.log('hi')") == "javascript"
    assert detect_language("#include <iostream>\nint main(){}") == "cpp"
    assert detect_language("public class Main { }") == "java"
    assert detect_language("x") is None
