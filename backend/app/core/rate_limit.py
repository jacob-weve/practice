import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.errors import RateLimitedError


@dataclass(frozen=True)
class RateWindow:
    limit: int
    remaining: int
    reset_seconds: int

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_seconds),
        }


async def enforce_fixed_window(
    redis: Redis, key: str, limit: int, window_seconds: int
) -> RateWindow:
    """고정 윈도우 카운터. 한도를 넘으면 남은 윈도우 시간을 Retry-After로 돌려준다."""
    now = int(time.time())
    window = now // window_seconds
    reset = window_seconds - now % window_seconds
    redis_key = f"rl:{key}:{window}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, window_seconds)
    if count > limit:
        raise RateLimitedError(retry_after=max(reset, 1))
    return RateWindow(limit=limit, remaining=limit - count, reset_seconds=reset)
