"""Per-language sandbox configuration.

Source files are mounted read-only at /work. Anything a compiler writes goes to /tmp (tmpfs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

JAVA_PUBLIC_CLASS = re.compile(r"public\s+(?:(?:final|abstract)\s+)*class\s+([A-Za-z_]\w*)")
JAVA_ANY_CLASS = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
JAVA_MAIN = re.compile(r"static\s+void\s+main\s*\(")


@dataclass(frozen=True)
class LanguageSpec:
    id: str
    label: str
    extension: str
    compile_cmd: str | None  # may contain {file} and {name}
    run_cmd: str
    mem_mb: int
    pids: int
    env: tuple[tuple[str, str], ...] = ()
    harness: str | None = None  # file in app/sandbox/harness/ copied to /work/.fixpoint_harness<ext>

    @property
    def compiled(self) -> bool:
        return self.compile_cmd is not None

    def entry_name(self, code: str) -> str:
        """Base file name for the source. Java needs it to match the public class."""
        if self.id != "java":
            return "main"
        match = JAVA_PUBLIC_CLASS.search(code)
        if match:
            return match.group(1)
        # No public class: pick the class that declares main(), else the first class.
        classes = list(JAVA_ANY_CLASS.finditer(code))
        for i, m in enumerate(classes):
            end = classes[i + 1].start() if i + 1 < len(classes) else len(code)
            if JAVA_MAIN.search(code, m.end(), end):
                return m.group(1)
        first = JAVA_ANY_CLASS.search(code)
        return first.group(1) if first else "Main"

    def filename(self, code: str) -> str:
        return f"{self.entry_name(code)}{self.extension}"

    def commands(self, code: str) -> tuple[str | None, str]:
        name = self.entry_name(code)
        file = f"/work/{name}{self.extension}"
        compile_cmd = self.compile_cmd.format(file=file, name=name) if self.compile_cmd else None
        return compile_cmd, self.run_cmd.format(file=file, name=name)


LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        id="python",
        label="Python",
        extension=".py",
        compile_cmd=None,
        run_cmd="python -u /work/.fixpoint_harness.py {file}",
        mem_mb=256,
        pids=64,
        env=(("PYTHONDONTWRITEBYTECODE", "1"), ("PYTHONUNBUFFERED", "1")),
        harness="python_harness.py",
    ),
    "javascript": LanguageSpec(
        id="javascript",
        label="JavaScript (Node)",
        extension=".js",
        compile_cmd=None,
        run_cmd="node {file}",
        mem_mb=256,
        pids=64,
    ),
    "cpp": LanguageSpec(
        id="cpp",
        label="C++ (GCC)",
        extension=".cpp",
        compile_cmd=("g++ -std=c++17 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -o /tmp/app {file}"),
        run_cmd="/tmp/app",
        mem_mb=512,
        pids=64,
        env=(("ASAN_OPTIONS", "detect_leaks=0:abort_on_error=0"), ("UBSAN_OPTIONS", "print_stacktrace=1")),
    ),
    "java": LanguageSpec(
        id="java",
        label="Java",
        extension=".java",
        compile_cmd="javac -J-XX:+UseSerialGC -J-XX:TieredStopAtLevel=1 -d /tmp {file}",
        run_cmd="java -XX:+UseSerialGC -XX:TieredStopAtLevel=1 -Xss64m -cp /tmp {name}",
        mem_mb=512,
        pids=128,
    ),
}


def detect_language(code: str) -> str | None:
    """Best-effort guess used only to warn the user. Never overrides their choice."""
    text = code.strip()
    if re.search(r"public\s+(?:final\s+)?class\s+\w+", text) or "System.out.print" in text:
        return "java"
    if "#include" in text and re.search(r"#include\s*<", text):
        return "cpp"
    if "console.log" in text or re.search(r"\b(?:const|let)\s+\w+\s*=", text) or "=>" in text:
        return "javascript"
    if re.search(r"^\s*def\s+\w+\(.*\)\s*:", text, re.M) or re.search(r"^\s*print\(", text, re.M):
        return "python"
    return None
