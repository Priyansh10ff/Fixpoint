# Fixpoint — Technical Design

Status: Phase 0. Describes the target architecture. Sections marked *(current)* describe what exists in the prototype today.

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
│   │   ├── api/
│   │   │   ├── run.py           # POST /api/run
│   │   │   ├── fix.py           # POST /api/fix (SSE)
│   │   │   ├── learn.py         # POST /api/learn/hints
│   │   │   └── meta.py          # GET /api/health, /api/providers
│   │   ├── sandbox/
│   │   │   ├── runner.py        # container lifecycle, limits, output capture
│   │   │   ├── languages.py     # per-language image, filename, compile/run commands
│   │   │   └── harness/         # runtime-context wrappers (py, js)
│   │   ├── agent/
│   │   │   ├── loop.py          # state machine
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
│       ├── lib/api.ts
│       └── App.tsx
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
client.containers.run(
    image=cfg.image,
    command=cmd,
    user="65534:65534",                 # nobody
    network_disabled=True,
    read_only=True,
    tmpfs={"/tmp": "rw,size=16m"},
    volumes={workdir: {"bind": "/work", "mode": "ro"}},  # code mounted read-only
    working_dir="/work",
    mem_limit="256m", memswap_limit="256m",
    nano_cpus=500_000_000,              # 0.5 CPU
    pids_limit=64,                      # stops fork bombs
    cap_drop=["ALL"],
    security_opt=["no-new-privileges"],
    runtime=settings.container_runtime, # "runsc" (gVisor) in production
    stdin_open=True, detach=True,
)
```

C++ and Java need a writable build directory: compile into `/tmp` (tmpfs).

Additional limits:
- Wall-clock timeout: compile 15 s, run 5 s (configurable). Container is killed and removed on timeout.
- Output cap: stdout/stderr truncated at 64 KB each.
- Code size cap: 100 KB. Stdin cap: 1 MB.
- Images pre-pulled on startup; a missing image returns a clear error instead of pulling during a request.
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
| Python | `harness.py` runs the user file with `runpy`, catches the exception, and serialises the last user frame with `traceback.TracebackException(capture_locals=True)` (values truncated with `reprlib`) |
| JavaScript | `harness.js` registers `uncaughtException`/`unhandledRejection`, prints a structured stack |
| C++ | AddressSanitizer + UBSan reports (out-of-bounds, use-after-free, signed overflow) plus exit signal |
| Java | Stack trace from stderr, parsed for exception type and line |

The harness writes context as one JSON line to stderr with a fixed prefix (`__FIXPOINT__`). The runner strips it from what the user sees.

## 4. Test cases

A test case is language-agnostic: `{ "input": "<stdin>", "expected": "<stdout>" }`.

Comparison: normalise trailing whitespace per line and trailing newlines, then exact match. An optional `float_tolerance` handles numeric output.

A program **passes** when every case exits 0 within the time limit and its output matches.

Generated regression case (Phase 3): the agent proposes an input and expected output that reproduces the bug. It is accepted only if:
1. the **original** code fails it, and
2. the **patched** code passes it.

Expected output comes from the model's reasoning, so it can be wrong. To limit this, the agent must also explain how the expected output was derived, and user-provided cases always take priority.

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

- `max_attempts` default 4; total time budget 90 s.
- Each retry includes the history: previous hypotheses, patches (as diffs) and their failures. The prompt tells the model not to repeat a rejected approach.
- "Best attempt" for UNVERIFIED = most test cases passed, then fewest lines changed.

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
| Unchanged | patched code identical to original |
| Deletion | > 40% of original non-blank lines removed |
| Swallow | new bare `except:` / `except Exception: pass` / empty `catch` around the failing region |
| Hardcode | expected output strings from test cases appearing as literals in the patch |
| Language | patch does not parse (Python `ast.parse`, others skipped) |

A rejected patch counts as an attempt and the reason is fed back to the model.

### 5.4 Learn mode

One LLM call after a VERIFIED fix produces:

```python
class HintLadder(BaseModel):
    nudge: str        # where to look, no answer
    concept: str      # the idea involved
    root_cause: str   # what is wrong and why
    fix_summary: str  # what to change; the diff unlocks after this
```

Hints are generated from the verified fix, so they never point to a wrong solution.

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
| Anthropic | anthropic | SDK | Strongest results for evals |

Configured through `.env`; providers without a key are hidden from `/api/providers`. Default local model: `qwen2.5-coder:7b`.

## 7. API

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/health` | — | `{status, docker, providers}` |
| GET | `/api/providers` | — | `[{name, models[]}]` |
| POST | `/api/run` | `{language, code, stdin?, tests?[]}` | `RunResult` + per-test results |
| POST | `/api/fix` | `{language, code, tests?[], mode: "fix"\|"learn", provider, model}` | SSE stream |
| GET | `/api/sessions/{id}` | — | session with attempts (Phase 6) |

### SSE events (`/api/fix`)

```
event: baseline        data: {run_result, tests}
event: attempt_start   data: {n}
event: diagnosis       data: {n, hypothesis, root_cause, concept_tags}
event: guard_reject    data: {n, reason}
event: verify          data: {n, run_result, tests, repro: {fails_original, passes_patched}}
event: hints           data: {nudge, concept, root_cause, fix_summary}       # learn mode
event: done            data: {status: "verified"|"unverified"|"no_bug"|"error",
                              final_code, diff, attempts, repro_case}
```

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

## 10. Known issues in the prototype *(current)*

| # | Issue | Fix in phase |
|---|---|---|
| 1 | Java file written as `main.java`; `public class Main` fails to compile | 1 |
| 2 | `_detect_language` silently overrides the user's chosen language | 1 |
| 3 | `ImageNotFound` message says the image is downloading but nothing pulls it | 1 |
| 4 | No CPU, pids or user limits; container runs as root | 1 |
| 5 | Code is mounted read-write | 1 |
| 6 | No stdin support | 1 |
| 7 | Debug sends the terminal text (e.g. "Ready to execute...") as logs if Run was not pressed first | 2 |
| 8 | One-shot fix, never re-run to verify | 2 |
| 9 | `@monaco-editor/react` installed but unused; textarea editor | 1 |
| 10 | Tailwind loaded from CDN script in `index.html` (dev-only) | 1 |
| 11 | Empty component files (`CodeEditor.jsx`, `DebugPanel.jsx`, `Terminal.jsx`) | 1 |
| 12 | CORS `*`, no rate limit, API URL hardcoded | 1 / 7 |
| 13 | Ollama called synchronously inside async route (blocks event loop) | 1 |
| 14 | Not a git repo; `venv/` and `__pycache__/` inside project | 0 |
| 15 | AI analysis is markdown but rendered as plain text (raw `**` visible) | 1 |
| 16 | Status bar shows hardcoded "Ln 1, Col 1" and "Online" | 1 |

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
