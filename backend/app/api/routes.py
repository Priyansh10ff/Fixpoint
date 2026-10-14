from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.debugger import SandboxUnavailable, debug_once
from app.agent.loop import DEFAULT_MAX_ATTEMPTS, fix_loop
from app.config import Settings
from app.llm.base import LLMError
from app.llm.registry import ProviderRegistry
from app.sandbox.runner import Sandbox
from app.schemas import (
    DebugRequest,
    DebugResponse,
    FixRequest,
    HealthResponse,
    ProvidersResponse,
    RunRequest,
    RunResult,
    TestRequest,
    TestSuiteResult,
)

router = APIRouter(prefix="/api")
log = logging.getLogger("fixpoint.api")

HEARTBEAT_S = 15.0


def get_sandbox(request: Request) -> Sandbox:
    return request.app.state.sandbox


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/health", response_model=HealthResponse)
async def health(sandbox: Sandbox = Depends(get_sandbox), settings: Settings = Depends(get_settings_dep)):
    docker_ok = await asyncio.to_thread(lambda: sandbox.client() is not None)
    images = await asyncio.to_thread(sandbox.image_status) if docker_ok else {}
    return HealthResponse(
        status="ok" if docker_ok else "degraded",
        docker=docker_ok,
        docker_error=None if docker_ok else sandbox.last_error,
        images=images,
        container_runtime=settings.container_runtime or "runc",
    )


@router.get("/providers", response_model=ProvidersResponse)
async def providers(registry: ProviderRegistry = Depends(get_registry)):
    return ProvidersResponse(default_provider=registry.default_provider, providers=await registry.describe())


@router.post("/run", response_model=RunResult)
async def run(req: RunRequest, sandbox: Sandbox = Depends(get_sandbox)):
    return await sandbox.run(req.code, req.language, req.stdin)


@router.post("/test", response_model=TestSuiteResult)
async def test(req: TestRequest, sandbox: Sandbox = Depends(get_sandbox)):
    """Run the program against every test case (one container, one compile) and compare outputs."""
    return await sandbox.run_tests(req.code, req.language, req.tests)


@router.post("/debug", response_model=DebugResponse)
async def debug(
    req: DebugRequest,
    sandbox: Sandbox = Depends(get_sandbox),
    registry: ProviderRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
):
    try:
        return await debug_once(
            code=req.code,
            language=req.language,
            stdin=req.stdin,
            provider_id=req.provider,
            model=req.model,
            sandbox=sandbox,
            registry=registry,
            settings=settings,
        )
    except SandboxUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.message) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/fix")
async def fix(
    req: FixRequest,
    request: Request,
    sandbox: Sandbox = Depends(get_sandbox),
    registry: ProviderRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
):
    """Agent loop as a Server-Sent Events stream. Validation errors are returned before streaming starts."""
    try:
        provider = registry.get(req.provider)
        model = await provider.resolve_model(registry.model_for(provider, req.model))
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in fix_loop(
                code=req.code,
                language=req.language,
                stdin=req.stdin,
                provider=provider,
                model=model,
                sandbox=sandbox,
                temperature=settings.llm_temperature,
                max_attempts=req.max_attempts or settings.max_fix_attempts or DEFAULT_MAX_ATTEMPTS,
                tests=req.tests,
            ):
                await queue.put(event)
        except Exception as exc:  # noqa: BLE001 - report unexpected failures to the client
            log.exception("fix loop crashed")
            await queue.put(
                (
                    "done",
                    {
                        "status": "error",
                        "message": f"Internal error: {exc}",
                        "final_code": None,
                        "diff": None,
                        "diagnosis": None,
                        "run": None,
                        "tests": None,
                        "attempts": 0,
                        "repro_case": None,
                    },
                )
            )
        finally:
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield _sse(*item)
        finally:
            if not task.done():
                task.cancel()  # client went away: stop calling the model and the sandbox
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
