"""Single-pass debugger. Phase 2 replaces this with the verify-and-retry loop."""

from __future__ import annotations

from app.agent.prompts import SYSTEM_PROMPT, build_debug_prompt
from app.config import Settings
from app.llm.base import Message
from app.llm.registry import ProviderRegistry
from app.sandbox.runner import Sandbox
from app.schemas import DebugResponse, Diagnosis


class SandboxUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def format_analysis(d: Diagnosis) -> str:
    return f"**Error:** {d.error_type}\n\n**Root cause:** {d.root_cause}\n\n**Fix:** {d.fix_summary}"


def _normalise(code: str) -> str:
    return "\n".join(line.rstrip() for line in code.strip().splitlines())


async def debug_once(
    *,
    code: str,
    language: str,
    stdin: str,
    provider_id: str | None,
    model: str | None,
    sandbox: Sandbox,
    registry: ProviderRegistry,
    settings: Settings,
) -> DebugResponse:
    # Always run server-side so the model sees the real output, not whatever the terminal shows.
    run = await sandbox.run(code, language, stdin)
    if run.status == "sandbox_error":
        raise SandboxUnavailable(run.message or "Sandbox error.")

    provider = registry.get(provider_id)
    chosen_model = await provider.resolve_model(registry.model_for(provider, model))
    diagnosis = await provider.complete_json(
        [Message("system", SYSTEM_PROMPT), Message("user", build_debug_prompt(code, language, stdin, run))],
        Diagnosis,
        model=chosen_model,
        temperature=settings.llm_temperature,
    )
    fixed = diagnosis.fixed_code.strip("\n") + "\n" if diagnosis.fixed_code.strip() else code
    diagnosis.fixed_code = fixed
    return DebugResponse(
        run=run,
        diagnosis=diagnosis,
        analysis=format_analysis(diagnosis),
        changed=_normalise(fixed) != _normalise(code),
        provider=provider.id,
        model=chosen_model,
    )
