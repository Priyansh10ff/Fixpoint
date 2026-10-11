<div align="center">

# Fixpoint

**Fixes you can run.**

A browser IDE with a debugging agent that runs your code in a sandbox, patches the bug, re-runs the patch to prove it works, and only then shows you the diff. Learn mode gives hints instead of answers.

![status](https://img.shields.io/badge/status-pre--release-orange)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![react](https://img.shields.io/badge/react-19-61DAFB?logo=react&logoColor=black)
![fastapi](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![docker](https://img.shields.io/badge/sandbox-Docker-2496ED?logo=docker&logoColor=white)
![ollama](https://img.shields.io/badge/LLM-Ollama%20%7C%20hosted-black)
![license](https://img.shields.io/badge/license-MIT-green)

</div>

---

![Fixpoint: running buggy code in the sandbox](docs/assets/editor-run.png)

<p align="center"><sub>Code runs in an isolated Docker container. Output and errors stream to the terminal panel.</sub></p>

![Fixpoint: proposed fix with diff and diagnosis](docs/assets/diff-analysis.png)

<p align="center"><sub>Side-by-side diff of the original and the fix, with a root-cause diagnosis. Apply or reject.</sub></p>

> Screenshots show the current prototype UI (v0). The target design is in [`docs/design.md`](docs/design.md).

---

## Why

Pasting an error into a chat assistant gives you a fix that was never run. It may not compile, may hide the symptom, or may delete the line that failed. And when the code runs but prints the wrong answer, there is no error to paste at all.

Fixpoint closes the loop:

```
run → capture failure + runtime state → hypothesise → patch → re-run in sandbox
    → still failing? feed the new failure back and retry (bounded)
    → passing?  generate a regression test that fails on the old code and passes on the new
    → show the diff, labelled VERIFIED
```

A fixed point is where applying a function stops changing the result. Fixpoint patches until the program stops failing.

## Features

| | Feature | Status |
|---|---|---|
| ▶ | Run Python, JavaScript (Node) and C++ in an isolated Docker container (no network, memory cap, timeout) | ✅ available |
| 🔍 | AI diagnosis of errors with root cause and full corrected code | ✅ available |
| ⇄ | Side-by-side diff with Apply / Reject | ✅ available |
| 🔒 | Local-first: runs fully offline with Ollama | ✅ available |
| 🔁 | Agent loop: patch → re-run → retry until the code passes | 🚧 Phase 2 |
| ✅ | VERIFIED / UNVERIFIED labels, generated regression test | 🚧 Phase 3 |
| 🧪 | Test cases (input + expected output) to catch "Wrong Answer" logic bugs | 🚧 Phase 3 |
| 🎓 | Learn mode: 4-level hint ladder before the fix is revealed | 🚧 Phase 4 |
| 📊 | Benchmark results on QuixBugs / DebugBench per model | 🚧 Phase 5 |
| ☁️ | Hosted providers (Groq, OpenRouter, Anthropic) alongside Ollama | 🚧 Phase 1 |
| ☕ | Java support | 🚧 Phase 1 |

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | React 19, Vite, Tailwind CSS, Monaco Editor, lucide-react |
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| Sandbox | Docker (Docker SDK for Python); gVisor in production |
| LLM | Ollama (local), Groq / OpenRouter / Anthropic (hosted) |
| Evals | QuixBugs, DebugBench |

## Architecture

```
Browser (React + Monaco)
   │  REST /run       SSE /fix (planned)
   ▼
FastAPI ──► agent loop ──► LLM provider (Ollama | Groq | OpenRouter | Anthropic)
   │
   ▼
Docker SDK ──► ephemeral container per run
               no network · memory/CPU/pids limits · timeout · removed after run
```

Full design: [`docs/technical.md`](docs/technical.md).

## Getting started

### Prerequisites

- [Node.js](https://nodejs.org/) 18+
- [Python](https://www.python.org/downloads/) 3.10+
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running)
- [Ollama](https://ollama.com/) (running)

### 1. Clone

```bash
git clone https://github.com/Priyansh10ff/fixpoint.git
cd fixpoint
```

### 2. Pull the model and sandbox images

```bash
ollama pull qwen2.5-coder

docker pull python:3.10-slim
docker pull node:18-alpine
docker pull gcc:latest
```

Pulling images up front avoids a slow first run.

### 3. Backend

```bash
cd backend
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows
venv\Scripts\activate

pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API runs at `http://localhost:8000` (interactive docs at `/docs`).

### 4. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 5. Try it

Paste this, press **Run**, then **Auto Debug**:

```python
def binary_search(arr, target):
    lo, hi = 0, len(arr)
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1

nums = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
print(binary_search(nums, 23))
print(binary_search(nums, 100))
```

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/run` | `{ "code": str, "language": "python" \| "javascript" \| "cpp" }` | `{ "exit_code": int, "logs": str }` |
| `POST` | `/debug` | `{ "code": str, "language": str, "logs": str, "model": str }` | `{ "analysis": str, "fixed_code": str }` |

The target API (`/api/run`, streaming `/api/fix`, providers, sessions) is specified in [`docs/technical.md`](docs/technical.md#7-api).

## Project structure

```
fixpoint/
├── backend/
│   ├── main.py          # FastAPI app and routes
│   ├── sandbox.py       # Docker execution sandbox
│   ├── ai_agent.py      # LLM diagnosis and fix
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx      # IDE layout, editor, diff, terminal, analysis
│       └── main.jsx
├── docs/
│   ├── product.md       # problem, users, USP, phases
│   ├── technical.md     # architecture, sandbox, agent loop, API, evals
│   ├── design.md        # layout, tokens, components, states
│   └── assets/          # screenshots
└── README.md
```

## Security

User code is treated as untrusted. Each run gets a fresh container with networking disabled, a memory limit and a wall-clock timeout, and the container is removed afterwards. Hardening planned for Phase 1 (non-root user, dropped capabilities, pids/CPU limits, read-only filesystem, gVisor) is listed in [`docs/technical.md`](docs/technical.md#32-container-hardening).

Do not expose the backend publicly before Phase 7: it has access to the Docker socket and no rate limiting yet.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 0 | Docs, rename, repo setup | 🟡 in progress |
| 1 | Sandbox hardening, Java, stdin, provider abstraction, Monaco, component split | ⬜ |
| 2 | Agent loop with live attempt timeline (SSE) | ⬜ |
| 3 | Test cases, generated regression test, VERIFIED labels | ⬜ |
| 4 | Learn mode (hint ladder) | ⬜ |
| 5 | Eval harness + published benchmark | ⬜ |
| 6 | Sessions, share links, example gallery | ⬜ |
| 7 | Deploy, rate limits, CI | ⬜ |
| 8 | Launch | ⬜ |

Details per phase: [`docs/product.md`](docs/product.md#8-build-phases).

## Contributing

Issues and pull requests are welcome.

1. Fork the repo and create a branch: `git checkout -b feat/your-change`
2. Commit with a clear message
3. Open a pull request describing what changed and how you tested it

## License

[MIT](LICENSE) © 2026 Priyansh Dugar
