from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import ProviderDeniedError, ProviderUnavailableError
from app.db.models import SocialAccount, SocialProvider


@dataclass(frozen=True)
class ProviderIdentity:
    provider_user_id: str
    email: str | None = None
    email_verified: bool = False
    is_private_email: bool = False
    display_name: str | None = None
    # 탈퇴 시 revoke가 필요한 제공자(애플)만 채운다. 저장 시 반드시 암호화한다.
    refresh_token: str | None = None
    scopes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoginContext:
    code: str
    redirect_uri: str
    code_verifier: str
    nonce: str
    state: str


class OAuthProvider(ABC):
    name: ClassVar[SocialProvider]
    authorize_endpoint: ClassVar[str]
    token_endpoint: ClassVar[str]
    scopes: ClassVar[tuple[str, ...]]
    # 제공자가 PKCE를 지원하면 code_challenge/code_verifier를 제공자에게도 전달한다.
    # 지원 여부와 무관하게 서버는 state에 바인딩된 challenge로 항상 PKCE를 검증한다.
    supports_pkce: ClassVar[bool] = False
    uses_nonce: ClassVar[bool] = True

    def __init__(self, settings: Settings, http: httpx.AsyncClient, redis: Redis) -> None:
        self.settings = settings
        self.http = http
        self.redis = redis

    @property
    @abstractmethod
    def client_id(self) -> str: ...

    def extra_authorize_params(self) -> dict[str, str]:
        return {}

    def build_authorize_url(
        self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str
    ) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": " ".join(self.scopes),
        }
        if self.uses_nonce:
            params["nonce"] = nonce
        if self.supports_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        params.update(self.extra_authorize_params())
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    @abstractmethod
    async def authenticate(self, ctx: LoginContext) -> ProviderIdentity: ...

    async def revoke(self, account: SocialAccount) -> None:  # noqa: B027
        """제공자 연결 해제. 저장된 토큰이 없어 해제할 수 없는 제공자는 아무것도 하지 않는다."""

    async def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        try:
            res = await self.http.post(
                self.token_endpoint, data=data, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            # 인가 코드는 1회용이므로 토큰 교환은 재시도하지 않는다 (CLAUDE.md §3.2-5).
            raise ProviderUnavailableError(log_detail=f"{self.name}:{type(exc).__name__}") from exc
        if res.status_code >= 500:
            raise ProviderUnavailableError(log_detail=f"{self.name}:token:{res.status_code}")
        try:
            body: dict[str, Any] = res.json()
        except ValueError as exc:
            raise ProviderUnavailableError(log_detail=f"{self.name}:token:non-json") from exc
        if res.status_code >= 400 or "error" in body:
            raise ProviderDeniedError(
                log_detail=f"{self.name}:token:{res.status_code}:{body.get('error')}"
            )
        return body
