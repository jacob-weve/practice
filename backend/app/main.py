from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.core.deps import DbDep, RedisDep
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIdMiddleware
from app.db.session import create_engine, create_sessionmaker
from app.llm.client import AnthropicProvider, CircuitBreaker, LlmClient, LlmProvider
from app.privacy.log_writer import TransformationLogWriter
from app.reply.router import router as reply_router
from app.tone.router import router as tone_router
from app.users.router import router as users_router


def create_app(
    settings: Settings | None = None,
    *,
    redis: Redis | None = None,
    llm_provider: LlmProvider | None = None,
) -> FastAPI:
    overridden = settings is not None
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.http_client = httpx.AsyncClient(timeout=settings.oauth_http_timeout_seconds)
        app.state.log_writer = TransformationLogWriter(app.state.sessionmaker)
        app.state.llm_client = LlmClient(
            llm_provider or AnthropicProvider(settings),
            settings,
            app.state.redis,
            CircuitBreaker(
                settings.llm_circuit_failure_threshold, settings.llm_circuit_open_seconds
            ),
        )
        try:
            yield
        finally:
            await app.state.http_client.aclose()
            await app.state.redis.aclose()
            await engine.dispose()

    configure_logging()
    app = FastAPI(
        title="TalkSoft API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept-Language",
            "X-Request-ID",
            "X-Client-Platform",
            "X-Requested-With",
        ],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    if overridden:
        app.dependency_overrides[get_settings] = lambda: settings

    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(_health_router(settings))
    api.include_router(auth_router)
    api.include_router(users_router)
    api.include_router(tone_router)
    api.include_router(reply_router)
    app.include_router(api)
    return app


def _health_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health")
    async def health(db: DbDep, redis: RedisDep) -> dict[str, Any]:
        status = {"status": "ok", "version": settings.app_version, "db": "ok", "redis": "ok"}
        try:
            await db.execute(text("SELECT 1"))
        except Exception:
            status.update(status="degraded", db="error")
        try:
            await redis.ping()
        except Exception:
            status.update(status="degraded", redis="error")
        return status

    return router


app = create_app()
