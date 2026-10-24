"""Run Fixpoint headless on benchmark tasks.

    python -m evals.run --dataset all --provider anthropic --model <model-id>
    python -m evals.run --dataset bench --baseline oracle      # harness self-check, no tokens

Each task goes through the same agent loop as the UI, with the task's visible test cases. The final
patch is then run against hidden cases the agent never saw, to measure whether "verified" really
means correct.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import time
from pathlib import Path

from app.agent.loop import fix_loop
from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMProvider, usage_scope
from app.llm.registry import build_registry
from app.sandbox.runner import Sandbox
from evals import bench, quixbugs
from evals.baselines import BASELINES, current_task
from evals.report import RESULTS_DIR, TaskRecord, load_runs, results_markdown, summarize, update_readme, write_run
from evals.tasks import Task, fingerprint, load_prepared, prepare, save_prepared

DATASETS = {"bench": bench.load, "quixbugs": quixbugs.load}
REPO_README = Path(__file__).resolve().parents[2] / "README.md"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


async def load_tasks(name: str, sandbox: Sandbox, refresh: bool) -> list[Task]:
    tasks = DATASETS[name]()
    fp = fingerprint(tasks)
    report = None if refresh else load_prepared(name, fp)
    if report is None:
        log(f"[{name}] validating {len(tasks)} tasks (reference must pass, bug must show up)…")
        images = sandbox.image_status()
        report = await prepare(tasks, sandbox, {lang for lang, ok in images.items() if ok})
        save_prepared(name, fp, report)
    for task_id, reason in report.dropped:
        log(f"[{name}] skipped {task_id}: {reason}")
    log(f"[{name}] {len(report.kept)} tasks ready")
    return report.kept


async def run_task(task: Task, provider: LLMProvider, model: str, sandbox: Sandbox, max_attempts: int) -> TaskRecord:
    token = current_task.set(task)
    done: dict = {}
    started = time.monotonic()
    try:
        with usage_scope() as usage:
            async for name, data in fix_loop(
                code=task.code,
                language=task.language,
                stdin="",
                provider=provider,
                model=model,
                sandbox=sandbox,
                max_attempts=max_attempts,
                tests=task.visible_tests(),
            ):
                if name == "done":
                    done = data
    except Exception as exc:  # noqa: BLE001 - one broken task must not stop the run
        done = {"status": "crash", "message": f"{type(exc).__name__}: {exc}", "attempts": 0}
        usage = None
    finally:
        current_task.reset(token)
    latency = time.monotonic() - started

    hidden_passed = 0
    final_code = done.get("final_code")
    if final_code and task.hidden:
        suite = await sandbox.run_tests(final_code, task.language, task.hidden_tests())
        hidden_passed = suite.passed if suite.status == "ok" else 0

    return TaskRecord(
        task_id=task.id,
        dataset=task.dataset,
        language=task.language,
        category=task.category,
        status=done.get("status", "crash"),
        attempts=int(done.get("attempts") or 0),
        latency_s=round(latency, 2),
        llm_calls=usage.calls if usage else 0,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        visible_total=len(task.visible),
        hidden_total=len(task.hidden),
        hidden_passed=hidden_passed,
        regression_case=bool(done.get("repro_case")),
        message=(done.get("message") or "")[:300],
    )


async def main_async(args: argparse.Namespace) -> int:
    settings: Settings = get_settings()
    if args.run_timeout:
        settings = settings.model_copy(update={"run_timeout_s": args.run_timeout})
    sandbox = Sandbox(settings)
    if sandbox.client() is None:
        log(f"Docker is not reachable: {sandbox.last_error}")
        return 2

    if args.baseline:
        provider: LLMProvider = BASELINES[args.baseline]()
        model = provider.id
    else:
        registry = build_registry(settings)
        try:
            provider = registry.get(args.provider)
            model = await provider.resolve_model(args.model or registry.model_for(provider, None))
        except LLMError as exc:
            log(str(exc))
            return 2

    names = list(DATASETS) if args.dataset == "all" else [args.dataset]
    tasks: list[Task] = []
    for name in names:
        tasks += await load_tasks(name, sandbox, args.refresh)
    if args.only:
        tasks = [t for t in tasks if any(key in t.id for key in args.only)]
    if args.limit:
        tasks = tasks[: args.limit]
    if not tasks:
        log("No tasks to run.")
        return 1

    log(
        f"Running {len(tasks)} tasks with {provider.id}/{model}, max {args.max_attempts} attempts, concurrency {args.concurrency}"
    )
    started_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()
    gate = asyncio.Semaphore(args.concurrency)
    records: list[TaskRecord] = []

    async def one(task: Task) -> None:
        async with gate:
            record = await run_task(task, provider, model, sandbox, args.max_attempts)
        records.append(record)
        hidden = f"hidden {record.hidden_passed}/{record.hidden_total}" if record.hidden_total else "no hidden"
        log(
            f"  [{len(records):>3}/{len(tasks)}] {record.status:<10} {task.id:<42} attempts={record.attempts} {hidden} {record.latency_s}s"
        )

    await asyncio.gather(*(one(t) for t in tasks))
    records.sort(key=lambda r: r.task_id)

    meta = {
        "started_at": started_at,
        "dataset": args.dataset,
        "provider": provider.id,
        "model": model,
        "baseline": bool(args.baseline),
        "max_attempts": args.max_attempts,
        "duration_s": round(time.monotonic() - t0, 1),
        "run_timeout_s": settings.run_timeout_s,
    }
    path = write_run(meta, records)
    runs = load_runs()
    (RESULTS_DIR / "RESULTS.md").write_text(results_markdown(runs), encoding="utf-8")
    if args.update_readme and REPO_README.exists():
        update_readme(REPO_README, runs)

    s = summarize(records)
    log("")
    log(
        f"verified {s['verified_pct']}% · correct on hidden {s['correct_pct']}% · false-verified {s['false_verified_pct']}%"
    )
    log(
        f"mean attempts {s['mean_attempts']} · p50 {s['p50_latency_s']}s · p95 {s['p95_latency_s']}s · tokens/task {s['mean_tokens']}"
    )
    log(f"results: {path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m evals.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--dataset", choices=["all", *DATASETS], default="all")
    who = p.add_mutually_exclusive_group()
    who.add_argument("--provider", help="ollama | groq | openrouter | anthropic (default: DEFAULT_PROVIDER)")
    who.add_argument("--baseline", choices=sorted(BASELINES), help="harness self-check instead of a model")
    p.add_argument("--model", help="model id (default: the provider's configured model)")
    p.add_argument("--max-attempts", type=int, default=4)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--limit", type=int, help="run only the first N tasks")
    p.add_argument("--only", nargs="*", help="run tasks whose id contains any of these strings")
    p.add_argument("--run-timeout", type=float, help="per-case time limit in seconds (default: RUN_TIMEOUT_S)")
    p.add_argument("--refresh", action="store_true", help="re-validate tasks instead of using the cache")
    p.add_argument("--update-readme", action="store_true", help="write the results table into README.md")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
