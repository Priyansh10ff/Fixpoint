# Fixpoint — Product

> Run your code. Fixpoint finds the bug, patches it, and proves the patch works before showing it to you. Or, in Learn mode, it walks you to the fix one hint at a time.

Status: Phase 5 harness complete; first model results pending. Last updated: 2026-10-22.

---

## 1. Problem

When code breaks, the default workflow today is: copy the error, paste it into a chat assistant, copy the answer back, run again, repeat. That loop has three problems:

1. **Unverified answers.** The assistant never runs the code. Suggested fixes are plausible text, not tested patches. A large share of "fixes" either do not compile, fix the symptom but not the cause, or silently delete the failing line.
2. **Missing context.** A stack trace alone rarely explains a bug. The useful information (variable values at the crash, the input that triggered it, the expected output) is lost when you paste.
3. **No learning.** For students, getting a finished fix teaches nothing. The next bug of the same kind costs the same time.

Logic bugs make it worse: when code runs without crashing but prints the wrong answer (the classic "Wrong Answer" on Codeforces or LeetCode), there is no error to paste at all.

## 2. What Fixpoint does

Fixpoint is a browser IDE with an agent that treats debugging as a loop, not a single answer:

```
run → capture failure + runtime state → hypothesise → patch → re-run in sandbox
    → still failing? feed the new failure back and try again (bounded)
    → passing? generate a regression test that fails on the old code and passes on the new code
    → only then show the diff, marked VERIFIED
```

The name comes from maths: a fixed point is where applying a function stops changing the result. Fixpoint keeps patching until the program stops failing.

### Two modes

| | **Fix mode** | **Learn mode** |
|---|---|---|
| For | Developers who want the bug gone | Students and anyone learning a language or DSA |
| Output | Verified diff + root cause + regression test | Hint ladder: nudge → concept → root cause → fix |
| Verification | Always | Always (the final fix is still verified) |
| Goal | Time saved | Skill gained |

## 3. USP (what makes it different)

1. **Every fix is executed before it is shown.** A fix is labelled `VERIFIED` only if it ran in the sandbox, passed the user's test cases (if given), and passed a generated regression test that also failed on the original code. Otherwise it is shown as `UNVERIFIED` with the reason.
2. **Handles "Wrong Answer", not only crashes.** Users can attach input/expected-output cases, the same format used in competitive programming. The agent debugs against those, so logic bugs are in scope.
3. **Runtime context, not just a stack trace.** The sandbox harness captures local variables at the crash (Python), sanitizer reports (C++ with ASan/UBSan), and full stack traces (JS), and passes them to the model.
4. **Published numbers.** A built-in eval harness runs Fixpoint on public bug datasets (QuixBugs, a subset of DebugBench) and reports verified-fix rate, average iterations and cost per model. Claims in this README are backed by those runs.
5. **Local-first, cloud-optional.** Runs fully offline with Ollama. The hosted demo uses a cloud provider. Same code path, swapped by config.
6. **Teaches when asked.** Learn mode gives graded hints instead of answers, with the verified fix kept behind the last step.

### Honest positioning

- Fixpoint is not trying to replace Cursor, Copilot or Claude Code. Those are editors and agents for whole repositories.
- Fixpoint is scoped to **single-file programs**: practice problems, scripts, assignments, interview prep, small reproductions of bugs. In that scope it can verify every fix, which repo-scale tools usually cannot.
- The defensible part is the verification loop + eval numbers, not the UI.

## 4. Target users

| Persona | Situation | What they need |
|---|---|---|
| **CP / DSA student** | Solution gets Wrong Answer or TLE on a hidden case | Find the failing input, understand the logic error |
| **CS undergrad** | Lab assignment crashes, first time seeing segfaults or recursion errors | Explanation they can learn from, not just a fix |
| **Developer** | Small script or snippet throws, wants a fast verified fix | Correct patch, no back-and-forth |
| **Privacy-sensitive user** | Cannot paste code into a cloud chat | Local model via Ollama, nothing leaves the machine |

Primary user for v1: **CP / DSA students and CS undergrads.** Clear pain, clear test format, easy to reach (college, Codeforces, LeetCode communities).

## 5. Core user stories

- As a user, I can write or paste code in Python, JavaScript, C++ or Java and run it in a sandbox with stdin.
- As a user, I can add test cases (input + expected output) and see pass/fail per case.
- As a user, I can press **Fix** and watch each attempt live: hypothesis, patch, re-run result.
- As a user, I see a diff of the final fix labelled VERIFIED or UNVERIFIED, plus a root-cause explanation, and can apply or reject it.
- As a user, I get the generated regression test so I know which input broke my code.
- As a learner, I can switch to **Learn** mode and reveal hints one level at a time.
- As a user, I can pick the model/provider (Ollama local, Groq, OpenRouter, Anthropic).
- As a visitor, I can see a benchmark table showing how well each model performs.

## 6. Scope

**In scope (v1)**
- Single-file programs, 4 languages: Python, JavaScript (Node), C++, Java
- Runtime errors, compile errors, wrong output vs. given test cases, timeouts
- Fix mode + Learn mode
- Ollama + one hosted provider for the demo
- Eval harness with published results

**Out of scope (v1)**
- Multi-file projects, package installs, network access from user code
- IDE plugins, GitHub integration
- Accounts beyond what is needed for rate limiting
- Collaborative editing

## 7. Success metrics

| Metric | Target for v1 |
|---|---|
| Verified-fix rate on QuixBugs (Python), hosted model | ≥ 80% |
| Verified-fix rate on QuixBugs (Python), local 7B model | ≥ 50% |
| Median iterations to verified fix | ≤ 2 |
| p50 time from "Fix" to first result (hosted) | < 15 s |
| False VERIFIED (fix labelled verified but wrong on hidden tests) | < 5% |
| Sandbox escape / abuse incidents | 0 |

## 8. Build phases

Each phase ends in something that runs and can be demoed.

### Phase 0 — Foundation & docs  ✅
- Rename to Fixpoint, write `docs/` (product, technical, design) and README
- Initialise git repo, `.gitignore` for `venv/`, `__pycache__/`, `node_modules/`
- Record known bugs in the current prototype (see technical.md §10)
- **Done when:** repo pushed with docs, README, screenshots

### Phase 1 — Solid core  ✅
- Restructure backend into `app/` modules (api, sandbox, agent, llm)
- Harden the sandbox (non-root, cap drop, pids/CPU/memory limits, read-only FS, output cap)
- Fix Java filename bug, remove silent language auto-override, add stdin
- LLM provider abstraction: Ollama, Groq/OpenRouter (OpenAI-compatible), Anthropic
- Frontend: Monaco editor, split `App.jsx` into components, proper Tailwind install (no CDN), API client module
- Backend tests with pytest
- **Done when:** run works for all 4 languages with stdin, any provider can be selected

### Phase 2 — Agent loop (the core USP)  ✅
- Runtime context harness per language (locals at crash, sanitizers, stack traces)
- Agent state machine: run → diagnose → patch → verify → retry (bounded)
- Patch guards (reject deleting the failing code, blanket try/except, hardcoding expected output)
- Server-Sent Events stream of attempts to the UI; live attempt timeline
- **Done when:** a buggy program gets fixed over multiple attempts and the UI shows each step

### Phase 3 — Test cases & verification  ✅
- Test case panel: input + expected output, per-case pass/fail
- Agent generates a regression case: must fail on original, pass on patched
- VERIFIED / UNVERIFIED labelling with reasons
- **Done when:** a "Wrong Answer" bug (no crash) is found and fixed with a generated failing input

### Phase 4 — Learn mode  ✅
- Hint ladder (4 levels), generated once per session, revealed progressively
- Concept tags (e.g. off-by-one, integer overflow, mutable default argument)
- "Explain this fix" on any diff
- **Done when:** a learner can solve a bug using hints without seeing the patch

### Phase 5 — Evals  *(harness ✅, results pending)*
- `evals/` harness: run Fixpoint headless on QuixBugs (31 Python programs) and fixpoint-bench (13 tasks, 4 languages). DebugBench dropped: it has no runnable tests
- Metrics: verified-fix rate, pass@1, avg iterations, tokens, latency, false-verified rate
- Results written to JSON + a Markdown table, embedded in README
- **Done when:** README shows a real benchmark table for at least 2 models

### Phase 6 — Sessions & polish
- SQLite persistence for sessions and attempts, shareable read-only session links
- Example bug gallery (one-click load)
- Keyboard shortcuts, empty/error states, onboarding hint
- **Done when:** a session can be shared by link and replayed

### Phase 7 — Deploy & hardening
- Frontend on Vercel; backend + Docker on a VPS/Fly.io machine with gVisor (`runsc`)
- Rate limiting, request size limits, CORS allow-list, optional GitHub login for the hosted demo
- CI (lint, tests, build), health checks, basic logging/metrics
- **Done when:** public URL is live and survives an abuse test (fork bomb, infinite loop, memory bomb)

### Phase 8 — Launch
- 60–90 s demo video, README GIF
- Write-up with eval numbers
- Post on X / LinkedIn, submit to relevant communities
