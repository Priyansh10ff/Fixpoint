# Fixpoint — Design

Status: Phase 0. The current prototype uses a VS Code clone look (`#1e1e1e`, blue accent). This document defines the target design. It is applied in Phases 1–4.

---

## 1. Principles

1. **Terminal-brutalist, not "AI product".** Dark, flat, monospace-led, hard edges, visible grid lines. No gradients, glow, sparkle icons or chat bubbles.
2. **Show the work.** The agent's attempts are the product. Every hypothesis, patch and re-run is visible in order, like a build log.
3. **Status is never ambiguous.** VERIFIED, UNVERIFIED, FAILED and RUNNING each have one colour and one label, used everywhere.
4. **The user stays in control.** Nothing changes the editor without an explicit Apply.
5. **Plain copy.** Short, factual labels. No "Let me help you!", no exclamation marks.

## 2. Layout

Desktop-first (≥ 1280 px). Three regions, all resizable.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ FIXPOINT  ▸ main.py   [python ▾]        [Fix | Learn]  [model ▾]  [RUN] [FIX] │  toolbar 44px
├───────────────────────────────────────────────┬──────────────────────────────┤
│                                               │ AGENT                         │
│  1  def binary_search(arr, x):                │ ─────────────────────────────│
│  2      lo, hi = 0, len(arr)                  │ 00 BASELINE    FAIL  IndexErr │
│  3      while lo <= hi:                       │ 01 ATTEMPT     ✕ 2/3 tests    │
│  4          mid = (lo + hi) // 2              │    hi should be len-1 …       │
│  ...                                          │ 02 ATTEMPT     ✓ 3/3 + repro  │
│                                               │ ─────────────────────────────│
│            editor / diff  (Monaco)            │ ■ VERIFIED in 2 attempts      │
│                                               │ [APPLY] [REJECT] [VIEW TEST]  │
│                                               │                               │  right panel 380px
├───────────────────────────────────────────────┴──────────────────────────────┤
│ [OUTPUT] [TESTS 3] [ANALYSIS]                                                 │
│ $ python main.py                                                              │  bottom panel 240px
│ Traceback (most recent call last): ...                                        │
├──────────────────────────────────────────────────────────────────────────────┤
│ ● docker ok   ollama · qwen2.5-coder:7b   py 3.12   ln 4 col 9      0.41s     │  status bar 24px
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Toolbar:** wordmark, file name, language, mode toggle, model picker, Run, Fix.
- **Editor:** Monaco. Switches to Monaco diff editor (side-by-side, original left) when a fix is ready.
- **Agent panel (right):** attempt timeline + final verdict + actions. In Learn mode it shows the hint ladder instead of the diff actions.
- **Bottom panel:** Output (stdout/stderr), Tests (cases + pass/fail), Analysis (root cause markdown).
- **Status bar:** sandbox health, provider/model, runtime version, cursor, last run duration.

Below 1024 px: agent panel becomes a bottom sheet tab. Below 768 px: read-only view (code + result), editing not supported.

## 3. Design tokens

### Colour (dark only for v1)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0b0c0e` | app background |
| `--surface` | `#111316` | panels |
| `--surface-2` | `#171a1e` | hover, inputs |
| `--line` | `#24282e` | 1px borders, grid lines |
| `--text` | `#e6e6e3` | primary text |
| `--text-dim` | `#8a8f98` | secondary text, line numbers |
| `--text-mute` | `#555b63` | disabled, placeholders |
| `--accent` | `#d4ff3a` | primary action (FIX), focus ring, wordmark cursor |
| `--ok` | `#3ddc84` | VERIFIED, passing test |
| `--warn` | `#ffb020` | UNVERIFIED, guard rejected |
| `--err` | `#ff4d4d` | FAIL, runtime error |
| `--run` | `#5ab0ff` | RUNNING |
| `--diff-add` | `rgba(61,220,132,.12)` | diff added lines |
| `--diff-del` | `rgba(255,77,77,.12)` | diff removed lines |

Contrast: all text tokens on `--bg`/`--surface` meet WCAG AA (≥ 4.5:1) except `--text-mute`, which is used only for non-essential text.

### Typography

| Role | Font | Size / weight |
|---|---|---|
| Code, logs, labels, buttons | JetBrains Mono | 13px / 400, labels 11px / 600 uppercase, letter-spacing .06em |
| Prose (analysis, hints) | Inter | 14px / 400, line-height 1.6 |
| Wordmark | JetBrains Mono | 14px / 700, `FIXPOINT_` with blinking accent cursor |

### Spacing, shape, motion

- 4px base grid; panel padding 12px; toolbar items gap 8px.
- Border radius **0** for panels and buttons. 2px only on tags.
- Borders, not shadows. No elevation.
- Motion: 120ms ease-out for state changes; new timeline rows slide in 8px. Respect `prefers-reduced-motion`.

## 4. Components

| Component | Notes |
|---|---|
| **Button** | Primary: `--accent` fill, black text, uppercase mono. Secondary: 1px `--line` outline. Destructive: `--err` text. Keyboard hint shown on hover (`⌘↵`). |
| **Status tag** | `[VERIFIED]` `[UNVERIFIED]` `[FAIL]` `[RUNNING]` in square brackets, colour from status token, mono 11px. |
| **Attempt row** | `NN TYPE  STATUS  summary`; expandable to show hypothesis, diff vs previous attempt, test results, guard reason. |
| **Test case card** | Input / Expected / Actual in three mono blocks; pass/fail tag; `generated` badge for repro cases. |
| **Hint ladder** | 4 locked rows (Nudge, Concept, Root cause, Fix). Each row has a `REVEAL` button; the diff unlocks only after level 4. Counter: "2 of 4 hints used". |
| **Verdict block** | Large status tag, attempts count, duration, and Apply / Reject / View test buttons. |
| **Model picker** | Grouped by provider; local models marked `local`; unavailable providers greyed with the reason. |
| **Terminal** | Mono, preserves ANSI colours, 64 KB cap message at the end when truncated. |

## 5. States

| State | Editor | Agent panel | Primary action |
|---|---|---|---|
| Empty | placeholder + "Load example" link | short explanation of Run vs Fix | RUN disabled |
| Idle | editable | last verdict or empty | RUN, FIX |
| Running | read-only, subtle top progress bar | — | CANCEL |
| Fixing | read-only | timeline streams in | CANCEL |
| Verified | diff view | verdict `[VERIFIED]` | APPLY |
| Unverified | diff of best attempt | verdict `[UNVERIFIED]` + reason list | APPLY (secondary), RETRY |
| No bug | editable | "All tests pass. Nothing to fix." | — |
| Sandbox down | editable | banner: Docker not reachable + how to start it | RUN disabled |
| Provider down | editable | banner: model not reachable | FIX disabled |

## 6. Key flows

**Fix mode**
1. Write code → optionally add tests → `FIX` (or `⌘⇧↵`).
2. Baseline run appears as row 00; attempts stream in.
3. On VERIFIED, the editor switches to diff; the generated test appears in Tests with a `generated` badge.
4. Apply replaces the editor content and re-runs automatically to show green output.

**Learn mode**
1. Same start. Timeline is collapsed to "Working…" so the answer is not leaked.
2. Hint ladder appears. User reveals hints one at a time and can edit code in between.
3. If the user's own edit passes all tests, show "Solved with N hints" and offer to compare with Fixpoint's fix.

## 7. Keyboard

| Action | Shortcut |
|---|---|
| Run | `⌘/Ctrl + ↵` |
| Fix | `⌘/Ctrl + ⇧ + ↵` |
| Apply fix | `⌘/Ctrl + Y` |
| Reject fix | `Esc` |
| Toggle mode | `⌘/Ctrl + M` |
| Focus tests | `⌘/Ctrl + T` |

## 8. Accessibility

- All actions reachable by keyboard; visible 2px `--accent` focus ring.
- Status always shown as text label, never colour alone.
- Timeline uses `aria-live="polite"` so screen readers announce new attempts.
- Diff view offers an inline (unified) mode for narrow screens and screen readers.

## 9. Brand

- Name: **Fixpoint**. Wordmark: `FIXPOINT_` in JetBrains Mono bold, the underscore is an `--accent` blinking cursor.
- Icon: a small square split by a diagonal (a function crossing `y = x`, the fixed-point line), single colour.
- Tagline: "Fixes you can run."
- Voice: plain, short, factual. Report what happened ("Attempt 2 passed 3/3 tests") rather than narrate ("Great news!").
