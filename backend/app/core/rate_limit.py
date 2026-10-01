import time

from redis.asyncio import Redis

from app.core.errors import RateLimitedError


async def enforce_fixed_window(redis: Redis, key: str, limit: int, window_seconds: int) -> None:
    """고정 윈도우 카운터. 한도를 넘으면 남은 윈도우 시간을 Retry-After로 돌려준다."""
    window = int(time.time()) // window_seconds
    redis_key = f"rl:{key}:{window}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, window_seconds)
    if count > limit:
        retry_after = window_seconds - int(time.time()) % window_seconds
        raise RateLimitedError(retry_after=max(retry_after, 1))
