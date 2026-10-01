from typing import Annotated

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.llm.client import LlmClient


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_http_client(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient = request.app.state.http_client
    return client


def get_llm_client(request: Request) -> LlmClient:
    client: LlmClient = request.app.state.llm_client
    return client


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]
LlmClientDep = Annotated[LlmClient, Depends(get_llm_client)]
