import json
from datetime import timedelta

import httpx
import respx
from fastapi import FastAPI
from sqlalchemy import select

from app.auth.service import REVOKE_QUEUE_KEY
from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import LlmTier, LogStatus, TransformationLog, TransformKind
from app.jobs import (
    REVOKE_DEAD_LETTER_KEY,
    REVOKE_MAX_ATTEMPTS,
    process_revoke_queue,
    purge_expired_logs,
)


async def test_purge_deletes_only_expired_logs(app: FastAPI) -> None:
    async with app.state.sessionmaker() as db:
        for days in (-1, 1):
            db.add(
                TransformationLog(
                    request_id=f"r{days}",
                    kind=TransformKind.TONE_TRANSFORM,
                    model_tier=LlmTier.LIGHT,
                    model_id="m",
                    status=LogStatus.SUCCESS,
                    expires_at=utcnow() + timedelta(days=days),
                )
            )
        await db.commit()

    assert await purge_expired_logs(app.state.sessionmaker) == 1
    async with app.state.sessionmaker() as db:
        remaining = (await db.execute(select(TransformationLog.request_id))).scalars().all()
    assert remaining == ["r1"]


async def test_revoke_queue_retries_then_dead_letters(
    app: FastAPI, settings: Settings, mock_http: respx.MockRouter
) -> None:
    redis = app.state.redis
    await redis.rpush(
        REVOKE_QUEUE_KEY,
        json.dumps({"provider": "kakao", "provider_user_id": "ok", "token_enc": None}),
        json.dumps({"provider": "kakao", "provider_user_id": "bad", "token_enc": None}),
    )
    unlink = mock_http.post("https://kapi.kakao.com/v1/user/unlink")
    unlink.side_effect = lambda request: httpx.Response(
        200 if b"target_id=ok" in request.content else 500
    )

    async with httpx.AsyncClient() as http:
        first = await process_revoke_queue(redis, http, settings)
        assert (first.revoked, first.retried, first.dead) == (1, 1, 0)
        for _ in range(REVOKE_MAX_ATTEMPTS - 1):
            await process_revoke_queue(redis, http, settings)

    assert await redis.llen(REVOKE_QUEUE_KEY) == 0
    dead = [json.loads(x) for x in await redis.lrange(REVOKE_DEAD_LETTER_KEY, 0, -1)]
    assert [(d["provider_user_id"], d["attempts"]) for d in dead] == [("bad", REVOKE_MAX_ATTEMPTS)]
