from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["python", "javascript", "cpp", "java"]
RunStatus = Literal["ok", "runtime_error", "compile_error", "timeout", "oom", "sandbox_error"]


class RunRequest(BaseModel):
    language: Language
    code: str = Field(min_length=1, max_length=100_000)
    stdin: str = Field(default="", max_length=1_000_000)


class ErrorContext(BaseModel):
    """Where and how the program failed, extracted from the sandbox output."""

    error_type: str
    message: str = ""
    line: int | None = None
    function: str | None = None
    locals: dict[str, str] = {}


class RunResult(BaseModel):
    status: RunStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    truncated: bool = False
    language: Language
    message: str | None = None
    language_hint: Language | None = None
    context: ErrorContext | None = None


class TestCase(BaseModel):
    __test__ = False  # not a pytest test class

    id: str | None = None
    input: str = Field(default="", max_length=200_000)
    expected: str = Field(default="", max_length=200_000)
    source: Literal["user", "generated"] = "user"


TestVerdict = Literal["passed", "wrong_answer", "runtime_error", "compile_error", "timeout", "oom", "sandbox_error"]


class TestCaseResult(BaseModel):
    __test__ = False  # not a pytest test class

    index: int
    id: str | None = None
    source: Literal["user", "generated"] = "user"
    input: str
    expected: str
    actual: str = ""
    stderr: str = ""
    passed: bool
    verdict: TestVerdict
    exit_code: int | None = None
    context: ErrorContext | None = None


class TestSuiteResult(BaseModel):
    __test__ = False  # not a pytest test class

    language: Language
    status: Literal["ok", "compile_error", "sandbox_error"]
    message: str | None = None
    compile_output: str = ""
    passed: int
    total: int
    duration_ms: int = 0
    results: list[TestCaseResult] = []

    @property
    def all_passed(self) -> bool:
        return self.status == "ok" and self.total > 0 and self.passed == self.total


class TestRequest(BaseModel):
    __test__ = False  # not a pytest test class

    language: Language
    code: str = Field(min_length=1, max_length=100_000)
    tests: list[TestCase] = Field(min_length=1, max_length=20)


class DebugRequest(RunRequest):
    provider: str | None = None
    model: str | None = None


class ReproCase(BaseModel):
    input: str = Field(description="Standard input for the program.")
    expected: str = Field(
        description="The correct output for that input, derived from what the program is meant to do."
    )


class Diagnosis(BaseModel):
    """Structured output the model must return."""

    hypothesis: str = Field(
        default="", description="One sentence: the most likely cause of the failure, stated as a testable claim."
    )
    error_type: str = Field(
        description='Exact error name, e.g. "IndexError", "Wrong Answer", "Segmentation fault", or "None" if there is no bug.'
    )
    root_cause: str = Field(description="Markdown. Why the error happens, referencing line numbers.")
    fix_summary: str = Field(description="Markdown. What was changed and why it fixes the root cause.")
    fixed_code: str = Field(description="The complete corrected source file, without line numbers.")
    repro_case: ReproCase | None = Field(
        default=None,
        description=(
            "A small regression test: an input on which the ORIGINAL program fails (crashes or prints a wrong "
            "answer) and the correct expected output. Derive the expected output from the intended behaviour, "
            "never by running the buggy logic in your head."
        ),
    )


class FixRequest(DebugRequest):
    max_attempts: int | None = Field(default=None, ge=1, le=8)
    tests: list[TestCase] = Field(default=[], max_length=20)


class DebugResponse(BaseModel):
    run: RunResult
    diagnosis: Diagnosis
    analysis: str
    changed: bool
    provider: str
    model: str


class ProviderInfo(BaseModel):
    id: str
    label: str
    local: bool
    available: bool
    reason: str | None = None
    default_model: str | None = None
    models: list[str] = []


class ProvidersResponse(BaseModel):
    default_provider: str
    providers: list[ProviderInfo]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    docker: bool
    docker_error: str | None = None
    images: dict[str, bool]
    container_runtime: str
