"""주기 작업. 스케줄러(cron, ECS Scheduled Task 등)에서 실행한다.

uv run python -m app.jobs purge-logs      # 매일 03:00 KST: 보관 기간이 지난 품질 로그 파기
uv run python -m app.jobs revoke-queue    # 5분마다: 탈퇴 시 실패한 제공자 연결 해제 재시도
"""

import asyncio
import base64
import json
import logging
import sys
from dataclasses import dataclass

import httpx
from redis.asyncio import Redis
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.providers import get_provider
from app.auth.service import REVOKE_QUEUE_KEY
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.base import utcnow
from app.db.models import SocialAccount, SocialProvider, TransformationLog
from app.db.session import create_engine, create_sessionmaker

logger = logging.getLogger(__name__)

REVOKE_DEAD_LETTER_KEY = "oauth:revoke_dead"
REVOKE_MAX_ATTEMPTS = 5
REVOKE_BATCH = 100


async def purge_expired_logs(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    async with sessionmaker() as db:
        result = await db.execute(
            delete(TransformationLog).where(TransformationLog.expires_at < utcnow())
        )
        await db.commit()
    deleted = int(getattr(result, "rowcount", 0) or 0)
    logger.info("job.purge_logs", extra={"deleted": deleted})
    return deleted


@dataclass
class RevokeStats:
    revoked: int = 0
    retried: int = 0
    dead: int = 0


async def process_revoke_queue(
    redis: Redis, http: httpx.AsyncClient, settings: Settings, batch: int = REVOKE_BATCH
) -> RevokeStats:
    """큐에서 꺼내 다시 시도한다. 계속 실패하면 dead-letter로 옮겨 사람이 확인하게 한다."""
    stats = RevokeStats()
    # 실패한 항목은 뒤에 다시 넣으므로 같은 실행에서 다시 꺼내지 않게 시작 시점 길이만큼만 돈다.
    pending = min(batch, int(await redis.llen(REVOKE_QUEUE_KEY)))
    for _ in range(pending):
        raw = await redis.lpop(REVOKE_QUEUE_KEY)
        if not isinstance(raw, str | bytes):
            break
        item = json.loads(raw)
        provider = get_provider(SocialProvider(item["provider"]), settings, http, redis)
        # 사용자 행은 이미 지워졌으므로 해제에 필요한 값만으로 임시 객체를 만든다.
        account = SocialAccount(
            social_provider=SocialProvider(item["provider"]),
            provider_user_id=item["provider_user_id"],
            provider_refresh_token_enc=base64.b64decode(item["token_enc"])
            if item.get("token_enc")
            else None,
        )
        try:
            await provider.revoke(account)
            stats.revoked += 1
        except AppError:
            item["attempts"] = int(item.get("attempts", 0)) + 1
            if item["attempts"] >= REVOKE_MAX_ATTEMPTS:
                await redis.rpush(REVOKE_DEAD_LETTER_KEY, json.dumps(item))
                stats.dead += 1
            else:
                await redis.rpush(REVOKE_QUEUE_KEY, json.dumps(item))
                stats.retried += 1
    logger.info(
        "job.revoke_queue",
        extra={"revoked": stats.revoked, "retried": stats.retried, "dead": stats.dead},
    )
    return stats


async def _main(command: str) -> None:
    settings = get_settings()
    if command == "purge-logs":
        engine = create_engine(settings.database_url)
        try:
            await purge_expired_logs(create_sessionmaker(engine))
        finally:
            await engine.dispose()
    elif command == "revoke-queue":
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        async with httpx.AsyncClient(timeout=settings.oauth_http_timeout_seconds) as http:
            try:
                await process_revoke_queue(redis, http, settings)
            finally:
                await redis.aclose()
    else:
        raise SystemExit(f"unknown job: {command}")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else ""))
