# Fixpoint — Technical Design

Status: Phase 4 complete. Describes the target architecture; sections note what is implemented. §10 tracks prototype bugs and where they were fixed.

---

## 1. Architecture

```
┌──────────────────────────── Browser ────────────────────────────┐
│  React + Vite + Tailwind                                         │
│  Monaco editor · Monaco diff · test cases · attempt timeline     │
└───────────────┬───────────────────────────────▲─────────────────┘
                │ REST (run)                    │ SSE (fix stream)
┌───────────────▼───────────────────────────────┴─────────────────┐
│  FastAPI backend                                                 │
│                                                                  │
│  api/ ──► agent/loop.py (state machine) ──► llm/ (providers)     │
│              │                                  │                │
│              ▼                                  ├─ Ollama        │
│         sandbox/ (Docker SDK)                   ├─ Groq/OpenRouter (OpenAI-compatible)
│              │                                  └─ Anthropic     │
│  storage/ (SQLite)        evals/ (headless runner)               │
└──────────────┼──────────────────────────────────────────────────┘
               ▼
   Ephemeral Docker containers (one per run)
   python:3.12-slim · node:20-alpine · gcc:14 · eclipse-temurin:21
   no network · non-root · read-only · cpu/mem/pids limits · gVisor in prod
```

### Why this stack

| Choice | Reason |
|---|---|
| **FastAPI (Python)** | Best Docker SDK, easy async + SSE, Pydantic for structured LLM output, same language as the eval harness |
| **React + Vite** | Already in the prototype; client-only app, no SSR needed. Next.js adds nothing here |
| **Monaco** | Same editor as VS Code, built-in diff editor, syntax highlighting for all 4 languages |
| **Docker per run** | Strong isolation, per-language images, simple to reason about. gVisor adds a kernel boundary in production |
| **SSE over WebSockets** | The fix stream is one-directional (server → client). SSE is simpler, works through proxies, auto-reconnects |
| **SQLite** | Single-node app; sessions and attempts are small. Swap to Postgres only if needed |
| **OpenAI-compatible client** | Ollama, Groq and OpenRouter all expose `/v1/chat/completions`, so one adapter covers three providers |

## 2. Repository layout (target)

```
fixpoint/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, routers, startup (pre-pull images)
│   │   ├── config.py            # pydantic-settings, reads .env
│   │   ├── schemas.py           # request/response + LLM output models
│   │   ├── api/
│   │   │   └── routes.py        # /api/health, /providers, /run, /debug (Phase 2 adds /fix SSE)
│   │   ├── sandbox/
│   │   │   ├── runner.py        # container lifecycle, limits, output capture
│   │   │   ├── languages.py     # per-language filename, compile/run commands, limits
│   │   │   ├── context.py       # structured error context from stderr
│   │   │   └── harness/         # python_harness.py (locals at crash)
│   │   ├── agent/
│   │   │   ├── debugger.py      # single-pass diagnosis (/api/debug)
│   │   │   ├── learn.py         # hint ladder wrapper + explain_patch (Phase 4)
│   │   │   ├── loop.py          # agent state machine (/api/fix)
│   │   │   ├── prompts.py       # system + per-step prompts
│   │   │   ├── schemas.py       # Pydantic models for LLM output
│   │   │   ├── guards.py        # patch validation
│   │   │   └── testing.py       # test case execution + comparison
│   │   ├── llm/
│   │   │   ├── base.py          # LLMProvider protocol
│   │   │   ├── openai_compat.py # Ollama, Groq, OpenRouter
│   │   │   ├── anthropic.py
│   │   │   └── registry.py
│   │   └── storage/
│   │       └── db.py            # SQLModel: Session, Attempt
│   ├── evals/
│   │   ├── datasets/            # QuixBugs, DebugBench subset (downloaded by script)
│   │   ├── run_evals.py
│   │   └── results/
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── components/          # Editor, DiffView, Terminal, TestCases, Timeline, HintLadder, Toolbar
│       ├── hooks/               # useRun, useFixStream
│       ├── lib/                 # api.js, monaco.js, languages.js, storage.js
│       └── App.jsx
├── docs/
├── docker-compose.yml
└── README.md
```

## 3. Sandbox

### 3.1 Language config

| Language | Image | File | Compile | Run |
|---|---|---|---|---|
| Python | `python:3.12-slim` | `main.py` | — | `python -u harness.py main.py` |
| JavaScript | `node:20-alpine` | `main.js` | — | `node harness.js main.js` |
| C++ | `gcc:14` | `main.cpp` | `g++ -std=c++17 -O1 -g -fsanitize=address,undefined -o app main.cpp` | `./app` |
| Java | `eclipse-temurin:21-jdk` | `Main.java` | `javac Main.java` | `java -Xss8m Main` |

Java requires the file name to match the public class. The runner detects `public class (\w+)` and names the file accordingly.

Compile and run are separate steps with separate time limits so a compile error is reported as `compile_error`, not `runtime_error`.

### 3.2 Container hardening

```python
client.containers.create(
    image=image,
    command=["sh", "-c", script],        # compile (if any) → marker → exec run < /work/input.txt
    user="65534:65534",                  # nobody
    network_disabled=True,
    read_only=True,
    tmpfs={"/tmp": "rw,exec,nosuid,nodev,size=64m,mode=1777"},
    volumes={workdir: {"bind": "/work", "mode": "ro"}},  # code + input.txt, read-only
    working_dir="/tmp",
    mem_limit=f"{spec.mem_mb}m", memswap_limit=f"{spec.mem_mb}m",  # 256 MB; 512 MB for C++/Java
    nano_cpus=int(CPU_LIMIT * 1e9),      # 0.5 CPU default
    pids_limit=spec.pids,                # 64; 128 for the JVM
    cap_drop=["ALL"],
    security_opt=["no-new-privileges"],
    log_config=LogConfig(type="json-file", config={"max-size": "2m", "max-file": "1"}),
    runtime=CONTAINER_RUNTIME or default,  # "runsc" (gVisor) in production
)
```

Implemented in `backend/app/sandbox/runner.py`.

C++ and Java compile into `/tmp` (tmpfs, `exec` allowed). Compile and run happen in the same container; a compile failure exits with a sentinel code (200) before a run marker is printed, so compile errors, compile timeouts and run timeouts are told apart.

Additional limits:
- Wall-clock timeout: `run + compile (if compiled) + 3 s startup`, enforced with `container.wait(timeout)`. Container is killed and removed on timeout. (Phase 2: per-phase in-container timeouts.)
- Output cap: stdout/stderr truncated at 64 KB each.
- Code size cap: 100 KB. Stdin cap: 1 MB.
- Missing images are pulled in a background thread on startup; a run with a missing image returns `docker pull <image>` instead of pulling during the request.
- Concurrency: semaphore limits simultaneous containers (default 4).

### 3.3 Run result

```json
{
  "status": "ok | runtime_error | compile_error | timeout | oom | sandbox_error",
  "exit_code": 1,
  "stdout": "...",
  "stderr": "...",
  "duration_ms": 412,
  "context": { "exception": "IndexError", "line": 12, "locals": {"i": "5", "arr": "[1, 2, 3]"} }
}
```

### 3.4 Runtime context harness

| Language | How context is captured |
|---|---|
| Python | `app/sandbox/harness/python_harness.py` runs the user file with `runpy`, prints the normal traceback with harness frames removed, and writes the failing frame's function, line and locals (via `reprlib`, max 25) as one JSON line |
| JavaScript | stderr parsed for the error name, message and `main.js:<line>` |
| C++ | AddressSanitizer + UBSan reports (out-of-bounds, use-after-free, signed overflow) plus exit signal |
| Java | Stack trace from stderr, parsed for exception type and line |

The harness writes context as one JSON line to stderr with a fixed prefix (`__FIXPOINT_CTX__`). The runner strips it before truncation, so the user sees a plain traceback, and returns it as `RunResult.context` (`error_type, message, line, function, locals`). Other languages are parsed from stderr in `app/sandbox/context.py`; timeouts and OOM map to "Time Limit Exceeded" / "Memory Limit Exceeded".

## 4. Test cases *(implemented in Phase 3)*

A test case is language-agnostic: `{ "input": "<stdin>", "expected": "<stdout>" }` (max 20 per request).

**Execution** (`Sandbox.run_tests`): all cases run in **one container**, so compiled languages compile once. The shell script compiles, prints the run marker, then loops over `/work/tests/<i>.in`, running each case under `timeout <RUN_TIMEOUT_S>` and framing its stdout and stderr with `__FP_BEGIN__ i` / `__FP_END__ i <exit>` markers. The runner parses the frames back into per-case results; the Python harness context is split per case.

| Exit / condition | Verdict |
|---|---|
| 0 and output matches | `passed` |
| 0 and output differs | `wrong_answer` |
| 124 (`timeout`) | `timeout` |
| 137 (killed) | `oom` |
| other non-zero | `runtime_error` (with error context) |
| compile failed | every case `compile_error`, compiler output in `compile_output` |

**Comparison:** trailing whitespace on each line and trailing blank lines are ignored; everything else must match exactly. (Float tolerance is not implemented.)

A program **passes** when every case is `passed`.

**Generated regression case:** each diagnosis may include `repro_case` (input + expected output). After a patch passes, the case is run against the original and the patched program. It is **accepted** only if:
1. the **original** code fails it, and
2. the **patched** code passes it.

The expected output comes from the model's reasoning and can be wrong, so a rejected case is reported with the reason and ignored. Accepted cases are offered in the Tests tab ("Add to tests").

### Verdict rules

| Situation | Status |
|---|---|
| Test mode, all user cases pass after the patch (at least one failed before) | `verified` |
| Run mode (no tests), patched program runs cleanly and the regression case is accepted | `verified` |
| Run mode, runs cleanly, no accepted regression case | `fixed` (output unchecked) |
| Test mode, all cases pass on the original | `no_bug` (no model call) |
| Run mode, original runs cleanly | one diagnosis; any change is `unverified` |
| Progress made but not passing within the attempt budget | `partial` |
| No progress | `unresolved` |

Progress in test mode = more cases passing than the current base (without introducing a compile error).

## 5. Agent loop

### 5.1 State machine

```
            ┌──────────┐
            │  START   │
            └────┬─────┘
                 ▼
            ┌──────────┐  all pass, no error   ┌────────────┐
            │ BASELINE │──────────────────────►│ NO_BUG     │
            │  run     │                       └────────────┘
            └────┬─────┘
                 │ failure
                 ▼
       ┌───► DIAGNOSE (LLM) ──► hypothesis, root_cause, patched_code, repro_case
       │         │
       │         ▼
       │      GUARDS ── reject ──┐
       │         │ ok            │
       │         ▼               │
       │      VERIFY             │
       │   run patched on all    │
       │   cases + repro check   │
       │         │               │
       │   pass  │  fail         │
       │    ▼    └───────────────┤
       │ VERIFIED                │
       │                         ▼
       └─────────── attempts < max? ── no ──► UNVERIFIED (best attempt)
```

Implemented in `backend/app/agent/loop.py`. Run mode (no tests) is described below; test mode and the verdict rules are in §4.

- `max_attempts` defaults to 4 (`MAX_FIX_ATTEMPTS`, 1–8 per request).
- **Pass** (run mode) = the patched program re-runs with status `ok`. In test mode, every case must pass.
- Each retry prompt carries the history: previous hypotheses, patches as unified diffs, and their re-run results or guard rejection reasons. The model is told not to repeat them.
- **Progress rule:** if a patch changes the failure (different error type or line) without introducing a new compile error, the original error is considered fixed. The loop continues from that patch with a fresh history. This handles programs with more than one bug.
- **Verdicts:** `fixed` (a patch re-ran clean), `partial` (at least one error fixed, still failing; the partial patch is offered), `unresolved` (no progress), `no_bug` (baseline ran clean and the model found nothing), `unverified` (baseline ran clean but the model suggested a change that also runs; cannot be checked without tests), `error` (sandbox or model failure), `cancelled` (client disconnected).
- Rejected patches are never executed.

### 5.2 LLM output schema

```python
class Diagnosis(BaseModel):
    error_type: str            # "IndexError", "Wrong Answer", "Segfault", ...
    hypothesis: str            # one sentence
    root_cause: str            # markdown, references lines
    concept_tags: list[str]    # ["off-by-one", "loop-bounds"]
    patched_code: str          # full file
    repro_case: TestCase | None
    expected_derivation: str | None
```

Full-file replacement instead of unified diffs: programs are small, and models produce invalid diff hunks often. The diff for display is computed server-side with `difflib`.

Structured output: JSON-schema mode where the provider supports it (Ollama `format`, OpenAI-compatible `response_format`, Anthropic tool use). Fallback: extract the first JSON object and validate with Pydantic; one repair retry on validation failure.

### 5.3 Guards (reject before running)

| Guard | Rejects |
|---|---|
| Unchanged / empty | patch identical to the current code, or empty |
| Deletion | > 40% of original non-blank lines removed |
| Swallow | more silent broad handlers than before: `except:` / `except Exception:` with `pass`/`continue`/`return None`, empty `catch {}` (JS/Java), `catch (...) {}` (C++) |
| Hardcode | an expected test output (2+ chars) newly appearing as a quoted string literal in the patch. Unquoted numbers are not detected. |
| Language | patch does not parse (Python `ast.parse`, others skipped) |

A rejected patch counts as an attempt and the reason is fed back to the model.

### 5.4 Learn mode *(implemented in Phase 4)*

`POST /api/fix` with `"mode": "learn"` runs the same loop, wrapped by `app/agent/learn.py::learn_wrapper`. When the loop's `done` status is `verified`, `fixed` or `partial`, one more model call turns the executed patch into a hint ladder, emitted as a `hints` event just before `done`:

```python
class HintLadder(BaseModel):
    concepts: list[str]  # 1-3 tags, e.g. "loop bounds", "off-by-one"
    nudge: str           # where to look, as a question; no bug or fix named
    concept: str         # the general idea, not specific to this patch
    root_cause: str      # what is wrong here and why it fails; no code
    fix_summary: str     # the change in words; no code block
```

- The prompt contains the original program, the diagnosis, and the **diff of the patch that passed**, so hints point at a fix that was executed, not at the model's first guess.
- If no patch passed, `hints` is `{status: "unavailable"}`; if the extra call fails, `{status: "error"}`. The fix itself is never lost.
- Hiding is a UI concern: the stream still carries everything. The frontend hides hypotheses, guard reasons, regression cases, patch buttons, the Analysis tab and patched run results until all 4 hints are revealed or the learner's own edit passes (tests all pass, or a clean run where the original failed). That last case is reported as "solved with N of 4 hints".

`POST /api/explain` takes `{language, original, patched}` and returns `{explanation: {summary, why, concepts}, diff}`. The UI offers it on any diff (Explain button).

## 6. LLM providers

```python
class LLMProvider(Protocol):
    name: str
    async def complete_json(self, messages: list[Message], schema: type[BaseModel],
                            model: str, temperature: float = 0.1) -> BaseModel: ...
    async def list_models(self) -> list[str]: ...
```

| Provider | Adapter | Base URL | Use |
|---|---|---|---|
| Ollama | openai_compat | `http://localhost:11434/v1` | Local, default for dev |
| Groq | openai_compat | `https://api.groq.com/openai/v1` | Fast hosted demo |
| OpenRouter | openai_compat | `https://openrouter.ai/api/v1` | Many models for evals |
| Anthropic | anthropic | `https://api.anthropic.com/v1` (httpx, forced tool use) | Strongest results for evals |

Configured through `.env`; providers without a key are hidden from `/api/providers`. Default local model: `qwen2.5-coder:7b`.

## 7. API

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/health` | — | `{status, docker, providers}` |
| GET | `/api/providers` | — | `[{name, models[]}]` |
| POST | `/api/run` | `{language, code, stdin?}` | `RunResult` |
| POST | `/api/debug` | `{language, code, stdin?, provider?, model?}` | single-pass diagnosis (Phase 1; replaced by `/api/fix`) |
| POST | `/api/test` | `{language, code, tests[]}` | `TestSuiteResult` (implemented) |
| POST | `/api/fix` | `{language, code, stdin?, tests?[], mode?: "fix"\|"learn", provider?, model?, max_attempts?}` | SSE stream (implemented) |
| POST | `/api/explain` | `{language, original, patched, provider?, model?}` | `ExplainResponse` (implemented) |
| GET | `/api/sessions/{id}` | — | session with attempts (Phase 6) |

### SSE events (`/api/fix`, implemented)

```
event: start          data: {language, provider, model, max_attempts, mode: "tests"|"run", test_count}
event: baseline       data: {run: RunResult|null, tests: TestSuiteResult|null}
event: attempt_start  data: {n}
event: diagnosis      data: {n, hypothesis, error_type, root_cause, fix_summary, repro_case}
event: guard_reject   data: {n, reason}
event: patch          data: {n, code, diff, changed_lines}
event: verify         data: {n, run, tests, outcome: "passed" | "failed" | "progress"}
event: repro          data: {n, case, original, patched, fails_original, passes_patched, accepted, reason}
event: hints          data: {status: "ok"|"error"|"unavailable", based_on, ladder}       # learn mode only
event: done           data: {status, message, final_code, diff, diagnosis, run, tests, attempts, repro_case}
```

`status` in `done`: `verified | fixed | partial | unresolved | no_bug | unverified | error`. A `: keep-alive` comment is sent every 15 s while the model is thinking. If the client disconnects, the loop task is cancelled so no further model calls or containers run. Provider errors are returned as HTTP 502 before the stream starts.

## 8. Data model (Phase 6)

```
Session(id, created_at, language, original_code, mode, provider, model, status, final_code)
Attempt(id, session_id, n, hypothesis, root_cause, patched_code, guard_result, verify_result_json, tokens_in, tokens_out, latency_ms)
TestCase(id, session_id, input, expected, source: "user"|"generated")
```

## 9. Evals

- **Datasets:** QuixBugs (40 programs, Python and Java, one-line bugs, with tests); DebugBench subset (LeetCode-style, C++/Java/Python, categorised bug types).
- **Runner:** `python -m evals.run_evals --dataset quixbugs --lang python --provider groq --model <m>`; calls the same `agent.loop` used by the API, with dataset tests as user cases.
- **Hidden tests:** a held-out split of tests is not shown to the agent and is used to measure false-VERIFIED.
- **Metrics:** verified-fix rate, hidden-test pass rate, false-verified rate, mean attempts, p50/p95 latency, tokens per fix.
- **Output:** `evals/results/<date>-<dataset>-<model>.json` + `results.md` table copied into the README.

## 10. Known issues in the prototype

| # | Issue | Phase | Status |
|---|---|---|---|
| 1 | Java file written as `main.java`; `public class Main` fails to compile | 1 | ✅ fixed |
| 2 | `_detect_language` silently overrides the user's chosen language | 1 | ✅ fixed |
| 3 | `ImageNotFound` message says the image is downloading but nothing pulls it | 1 | ✅ fixed |
| 4 | No CPU, pids or user limits; container runs as root | 1 | ✅ fixed |
| 5 | Code is mounted read-write | 1 | ✅ fixed |
| 6 | No stdin support | 1 | ✅ fixed |
| 7 | Debug sends the terminal text (e.g. "Ready to execute...") as logs if Run was not pressed first | 2 | ✅ fixed (debug always re-runs server-side) |
| 8 | One-shot fix, never re-run to verify | 2 | ✅ fixed (agent loop re-runs every patch) |
| 9 | `@monaco-editor/react` installed but unused; textarea editor | 1 | ✅ fixed |
| 10 | Tailwind loaded from CDN script in `index.html` (dev-only) | 1 | ✅ fixed |
| 11 | Empty component files (`CodeEditor.jsx`, `DebugPanel.jsx`, `Terminal.jsx`) | 1 | ✅ fixed |
| 12 | CORS `*`, no rate limit, API URL hardcoded | 1 / 7 | ✅ CORS allow-list + env API URL; rate limit in Phase 7 |
| 13 | Ollama called synchronously inside async route (blocks event loop) | 1 | ✅ fixed |
| 14 | Not a git repo; `venv/` and `__pycache__/` inside project | 0 | ✅ fixed |
| 15 | AI analysis is markdown but rendered as plain text (raw `**` visible) | 1 | ✅ fixed |
| 16 | Status bar shows hardcoded "Ln 1, Col 1" and "Online" | 1 | ✅ fixed |

## 11. Security

- User code is untrusted: no network, non-root, read-only mounts, dropped capabilities, resource limits, gVisor in production.
- The backend holds the Docker socket, which is root-equivalent on the host. In production the backend runs on a dedicated VM that hosts nothing else.
- Prompt injection: user code may contain instructions to the model. The model's output only ever becomes code that runs in the same sandbox, so injection cannot escalate beyond the sandbox. Guards still apply.
- Rate limiting (per IP + per user): 30 runs/min, 5 fixes/min on the hosted demo.
- Secrets in `.env`, never sent to the frontend.

## 12. Deployment (Phase 7)

| Part | Where | Notes |
|---|---|---|
| Frontend | Vercel | static build, `VITE_API_URL` env |
| Backend + Docker | VPS (Hetzner / Oracle free tier) or Fly.io Machine | Docker + gVisor; Caddy for HTTPS |
| LLM | Groq / OpenRouter for the demo | Ollama for local use |
| CI | GitHub Actions | ruff, pytest, eslint, vite build |

Serverless platforms (Vercel functions, Render free tier) cannot run Docker containers, so the backend needs a VM. Alternative if a VM is not available: a hosted sandbox (E2B, Piston) behind the same `sandbox` interface.

## 13. Configuration

```env
# backend/.env
FIXPOINT_ENV=dev
CORS_ORIGINS=http://localhost:5173
CONTAINER_RUNTIME=runc            # runsc in production
RUN_TIMEOUT_S=5
COMPILE_TIMEOUT_S=15
MAX_CONCURRENT_RUNS=4
MAX_FIX_ATTEMPTS=4

DEFAULT_PROVIDER=ollama
DEFAULT_MODEL=qwen2.5-coder:7b
OLLAMA_BASE_URL=http://localhost:11434/v1
GROQ_API_KEY=
OPENROUTER_API_KEY=
ANTHROPIC_API_KEY=
```

```env
# frontend/.env
VITE_API_URL=http://localhost:8000
```
