from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.debugger import SandboxUnavailable, debug_once
from app.config import Settings
from app.llm.base import LLMError
from app.llm.registry import ProviderRegistry
from app.sandbox.runner import Sandbox
from app.schemas import (
    DebugRequest,
    DebugResponse,
    HealthResponse,
    ProvidersResponse,
    RunRequest,
    RunResult,
)

router = APIRouter(prefix="/api")


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
