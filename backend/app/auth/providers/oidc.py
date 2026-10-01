import json
from collections.abc import Iterable
from typing import Any

import httpx
import jwt
from redis.asyncio import Redis

from app.core.errors import IdTokenInvalidError, ProviderUnavailableError
from app.core.security import constant_time_equals

CLOCK_SKEW_SECONDS = 60
FORCED_REFRESH_INTERVAL_SECONDS = 60
ALLOWED_ALGORITHMS = ["RS256", "ES256"]


class JwksCache:
    """제공자 JWKS를 Redis에 캐시한다. kid 미스 시 분당 1회까지만 강제 갱신한다."""

    def __init__(self, http: httpx.AsyncClient, redis: Redis, ttl_seconds: int) -> None:
        self.http = http
        self.redis = redis
        self.ttl = ttl_seconds

    async def _fetch(self, provider: str, jwks_uri: str) -> list[dict[str, Any]]:
        try:
            res = await self.http.get(jwks_uri)
            res.raise_for_status()
            keys: list[dict[str, Any]] = res.json()["keys"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ProviderUnavailableError(log_detail=f"{provider}:jwks") from exc
        await self.redis.set(f"jwks:{provider}", json.dumps(keys), ex=self.ttl)
        return keys

    async def get_key(self, provider: str, jwks_uri: str, kid: str) -> dict[str, Any]:
        cached = await self.redis.get(f"jwks:{provider}")
        keys: list[dict[str, Any]] = json.loads(cached) if cached else []
        if not keys:
            keys = await self._fetch(provider, jwks_uri)
        key = _find(keys, kid)
        if key is None:
            allowed = await self.redis.set(
                f"jwks:{provider}:forced", "1", nx=True, ex=FORCED_REFRESH_INTERVAL_SECONDS
            )
            if allowed:
                key = _find(await self._fetch(provider, jwks_uri), kid)
        if key is None:
            raise IdTokenInvalidError(log_detail=f"{provider}:unknown_kid")
        return key


def _find(keys: Iterable[dict[str, Any]], kid: str) -> dict[str, Any] | None:
    return next((k for k in keys if k.get("kid") == kid), None)


async def verify_id_token(
    id_token: str,
    *,
    provider: str,
    jwks: JwksCache,
    jwks_uri: str,
    issuers: tuple[str, ...],
    audience: str,
    nonce: str | None,
    required_claims: tuple[str, ...] = ("iss", "aud", "exp", "iat", "sub"),
) -> dict[str, Any]:
    """검증 순서: 서명(JWKS, kid) → iss → aud → exp/iat → nonce (CLAUDE.md §3.2-3)."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise IdTokenInvalidError(log_detail=f"{provider}:malformed") from exc
    kid = header.get("kid")
    alg = header.get("alg")
    if not kid or alg not in ALLOWED_ALGORITHMS:
        raise IdTokenInvalidError(log_detail=f"{provider}:bad_header")

    jwk = await jwks.get_key(provider, jwks_uri, kid)
    try:
        signing_key = jwt.PyJWK(jwk).key
        claims: dict[str, Any] = jwt.decode(
            id_token,
            signing_key,
            algorithms=[alg],
            audience=audience,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": list(required_claims), "verify_iss": False},
        )
    except jwt.PyJWTError as exc:
        raise IdTokenInvalidError(log_detail=f"{provider}:{type(exc).__name__}") from exc

    # 구글은 iss가 두 가지 형식이라 PyJWT 단일 issuer 검증 대신 직접 비교한다.
    if claims.get("iss") not in issuers:
        raise IdTokenInvalidError(log_detail=f"{provider}:iss")
    if nonce is not None:
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not constant_time_equals(token_nonce, nonce):
            raise IdTokenInvalidError(log_detail=f"{provider}:nonce")
    return claims


def as_bool(value: Any) -> bool:
    """애플은 불리언 클레임을 "true"/"false" 문자열로 줄 때가 있다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False
