"""Model stand-ins for checking the harness itself, without spending tokens.

- oracle: returns the task's reference fix. Should score ~100% verified; anything lower is a bug in
  the harness, the sandbox, or the task (not in a model).
- echo: returns the buggy program unchanged. Should score 0%; anything higher means the harness
  counts fixes that did not happen.
"""

from __future__ import annotations

import json
from contextvars import ContextVar

from app.llm.base import LLMProvider, Message
from evals.tasks import Task

current_task: ContextVar[Task | None] = ContextVar("fixpoint_eval_task", default=None)


class _Baseline(LLMProvider):
    local = True

    def __init__(self):
        super().__init__(default_model=self.id)

    async def list_models(self) -> list[str]:
        return [self.id]

    def _code(self, task: Task) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    async def _complete(self, messages: list[Message], model: str, temperature: float, schema: dict) -> str:
        task = current_task.get()
        if task is None:
            raise RuntimeError("baseline provider used outside an eval task")
        props = schema.get("properties", {})
        if "fixed_code" not in props:  # hint ladder / explanation requests
            return json.dumps({k: "n/a" if k != "concepts" else [] for k in props})
        return json.dumps(
            {
                "hypothesis": f"{self.id} baseline",
                "error_type": "Unknown",
                "root_cause": f"{self.id} baseline",
                "fix_summary": f"{self.id} baseline",
                "fixed_code": self._code(task),
                "repro_case": None,
            }
        )


class OracleProvider(_Baseline):
    id = "oracle"
    label = "Oracle (reference fix)"

    def _code(self, task: Task) -> str:
        return task.reference


class EchoProvider(_Baseline):
    id = "echo"
    label = "Echo (no change)"

    def _code(self, task: Task) -> str:
        return task.code


BASELINES = {"oracle": OracleProvider, "echo": EchoProvider}
