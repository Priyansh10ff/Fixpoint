"""Per-task records → aggregate metrics → markdown."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
README_START = "<!-- BENCHMARK:START -->"
README_END = "<!-- BENCHMARK:END -->"


@dataclass
class TaskRecord:
    task_id: str
    dataset: str
    language: str
    category: str
    status: str  # done.status from the agent loop, or "crash"
    attempts: int
    latency_s: float
    llm_calls: int
    input_tokens: int
    output_tokens: int
    visible_total: int
    hidden_total: int
    hidden_passed: int
    regression_case: bool
    message: str = ""

    @property
    def has_patch(self) -> bool:
        return self.status in {"verified", "fixed", "partial", "unverified"}

    @property
    def correct(self) -> bool:
        """The final patch passes the visible cases (status verified) and every hidden case."""
        return self.status == "verified" and self.hidden_passed == self.hidden_total

    @property
    def false_verified(self) -> bool:
        return self.status == "verified" and self.hidden_passed < self.hidden_total


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 2)


def summarize(records: list[TaskRecord]) -> dict:
    n = len(records)
    verified = [r for r in records if r.status == "verified"]
    latencies = [r.latency_s for r in records]
    return {
        "tasks": n,
        "verified_pct": _pct(len(verified), n),
        "correct_pct": _pct(sum(r.correct for r in records), n),
        "false_verified_pct": _pct(sum(r.false_verified for r in records), len(verified)),
        "unresolved_pct": _pct(sum(r.status in {"unresolved", "partial"} for r in records), n),
        "errors": sum(r.status in {"error", "crash"} for r in records),
        # attempts needed to reach a verified fix (unresolved tasks always use the full budget)
        "mean_attempts": round(statistics.mean(r.attempts for r in verified), 2) if verified else 0.0,
        "p50_latency_s": _percentile(latencies, 0.5),
        "p95_latency_s": _percentile(latencies, 0.95),
        "mean_tokens": round(statistics.mean(r.input_tokens + r.output_tokens for r in records)) if records else 0,
        "regression_cases_pct": _pct(sum(r.regression_case for r in verified), len(verified)),
    }


def write_run(meta: dict, records: list[TaskRecord]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    name = (
        f"{meta['started_at'].replace(':', '').replace('-', '')}-{meta['dataset']}-{meta['provider']}-{meta['model']}"
    )
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    path = RESULTS_DIR / f"{safe}.json"
    by_dataset = {}
    for ds in sorted({r.dataset for r in records}):
        by_dataset[ds] = summarize([r for r in records if r.dataset == ds])
    payload = {
        "meta": meta,
        "summary": summarize(records),
        "by_dataset": by_dataset,
        "records": [asdict(r) for r in records],
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def load_runs() -> list[dict]:
    if not RESULTS_DIR.exists():
        return []
    runs = []
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return runs


HEADER = (
    "| Model | Dataset | Tasks | Verified | Correct on hidden tests | False-verified | Attempts to verify "
    "| p50 / p95 latency | Tokens / task |\n|---|---|---:|---:|---:|---:|---:|---:|---:|"
)


def table(runs: list[dict], include_baselines: bool = True) -> str:
    """Latest run per (provider, model, dataset), as a markdown table."""
    latest: dict[tuple, dict] = {}
    for run in runs:
        meta = run["meta"]
        if not include_baselines and meta.get("baseline"):
            continue
        for ds, summary in run["by_dataset"].items():
            key = (meta["provider"], meta["model"], ds)
            if key not in latest or meta["started_at"] > latest[key]["meta"]["started_at"]:
                latest[key] = {"meta": meta, "summary": summary}
    rows = []
    for (provider, model, ds), item in sorted(
        latest.items(), key=lambda kv: (kv[1]["meta"].get("baseline", False), kv[0])
    ):
        s = item["summary"]
        label = f"`{model}`" + (" *(baseline)*" if item["meta"].get("baseline") else f" · {provider}")
        rows.append(
            f"| {label} | {ds} | {s['tasks']} | {s['verified_pct']}% | {s['correct_pct']}% | "
            f"{s['false_verified_pct']}% | {s['mean_attempts']} | {s['p50_latency_s']}s / {s['p95_latency_s']}s | "
            f"{s['mean_tokens']:,} |"
        )
    return HEADER + "\n" + "\n".join(rows) if rows else HEADER


def results_markdown(runs: list[dict]) -> str:
    lines = [
        "# Fixpoint benchmark results",
        "",
        "Generated by `python -m evals.run`. Latest run per model and dataset.",
        "",
        table(runs),
        "",
        "**Verified**: the agent's verdict was VERIFIED (all visible test cases pass; at least one failed before).  ",
        "**Correct on hidden tests**: verified *and* the patch passes every held-out case the agent never saw.  ",
        "**False-verified**: share of verified fixes that fail a hidden case (lower is better).  ",
        "**Baselines**: `oracle` returns the known fix and `echo` returns the bug unchanged; they check the harness, not a model.",
        "",
        "## Runs",
        "",
    ]
    for run in sorted(runs, key=lambda r: r["meta"]["started_at"], reverse=True):
        m = run["meta"]
        lines.append(
            f"- {m['started_at']} · `{m['provider']}/{m['model']}` · {m['dataset']} · {run['summary']['tasks']} tasks · "
            f"max {m['max_attempts']} attempts · {m['duration_s']}s"
        )
    return "\n".join(lines) + "\n"


def update_readme(readme: Path, runs: list[dict]) -> bool:
    text = readme.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return False
    head, rest = text.split(README_START, 1)
    _, tail = rest.split(README_END, 1)
    block = f"{README_START}\n{table(runs)}\n{README_END}"
    readme.write_text(head + block + tail, encoding="utf-8")
    return True
