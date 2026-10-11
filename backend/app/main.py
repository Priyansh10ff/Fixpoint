from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import Settings, get_settings
from app.llm.registry import ProviderRegistry, build_registry
from app.sandbox.runner import Sandbox

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def create_app(
    settings: Settings | None = None,
    sandbox: Sandbox | None = None,
    registry: ProviderRegistry | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.prepull_images:
            threading.Thread(target=app.state.sandbox.prepull_missing, daemon=True).start()
        yield

    app = FastAPI(title="Fixpoint API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sandbox = sandbox or Sandbox(settings)
    app.state.registry = registry or build_registry(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
