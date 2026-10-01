import json
from dataclasses import asdict, dataclass
from typing import Any

from redis.asyncio import Redis

from app.core.security import generate_opaque

HANDOFF_TTL_SECONDS = 60


@dataclass(frozen=True)
class PendingAuthorization:
    provider: str
    nonce: str
    code_challenge: str
    redirect_uri: str


@dataclass(frozen=True)
class AppleHandoff:
    code: str
    state: str
    user: dict[str, Any] | None


class OAuthStateStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl = ttl_seconds

    async def save(self, state: str, pending: PendingAuthorization) -> None:
        await self.redis.set(f"oauth:state:{state}", json.dumps(asdict(pending)), ex=self.ttl)

    async def consume(self, state: str) -> PendingAuthorization | None:
        # 검증 성공/실패와 무관하게 1회만 읽히도록 GETDEL로 꺼낸다 (CLAUDE.md §3.2-2).
        raw = await self.redis.getdel(f"oauth:state:{state}")
        return PendingAuthorization(**json.loads(raw)) if raw else None

    async def save_apple_handoff(self, handoff: AppleHandoff) -> str:
        key = generate_opaque(24)
        await self.redis.set(
            f"oauth:handoff:{key}", json.dumps(asdict(handoff)), ex=HANDOFF_TTL_SECONDS
        )
        return key

    async def consume_apple_handoff(self, key: str) -> AppleHandoff | None:
        raw = await self.redis.getdel(f"oauth:handoff:{key}")
        return AppleHandoff(**json.loads(raw)) if raw else None
