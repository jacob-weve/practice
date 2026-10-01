import httpx
from redis.asyncio import Redis

from app.auth.providers.apple import AppleProvider
from app.auth.providers.base import LoginContext, OAuthProvider, ProviderIdentity
from app.auth.providers.google import GoogleProvider
from app.auth.providers.kakao import KakaoProvider
from app.auth.providers.naver import NaverProvider
from app.core.config import Settings
from app.core.errors import UnsupportedProviderError
from app.db.models import SocialProvider

PROVIDERS: dict[SocialProvider, type[OAuthProvider]] = {
    SocialProvider.KAKAO: KakaoProvider,
    SocialProvider.GOOGLE: GoogleProvider,
    SocialProvider.NAVER: NaverProvider,
    SocialProvider.APPLE: AppleProvider,
}


def parse_provider(raw: str) -> SocialProvider:
    try:
        return SocialProvider(raw)
    except ValueError as exc:
        raise UnsupportedProviderError() from exc


def get_provider(
    provider: SocialProvider, settings: Settings, http: httpx.AsyncClient, redis: Redis
) -> OAuthProvider:
    return PROVIDERS[provider](settings, http, redis)


__all__ = [
    "AppleProvider",
    "LoginContext",
    "OAuthProvider",
    "ProviderIdentity",
    "get_provider",
    "parse_provider",
]
