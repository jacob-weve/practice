import asyncio
from typing import Any

import httpx

from app.auth.providers.base import LoginContext, OAuthProvider, ProviderIdentity
from app.core.errors import ProviderDeniedError, ProviderUnavailableError
from app.db.models import SocialProvider

PROFILE_MAX_RETRIES = 2
PROFILE_BACKOFF_SECONDS = 0.2


class NaverProvider(OAuthProvider):
    """네이버는 OIDC를 지원하지 않으므로 Access Token으로 프로필 API를 호출해 신원을 확인한다."""

    name = SocialProvider.NAVER
    authorize_endpoint = "https://nid.naver.com/oauth2.0/authorize"
    token_endpoint = "https://nid.naver.com/oauth2.0/token"  # noqa: S105 (URL)
    profile_endpoint = "https://openapi.naver.com/v1/nid/me"
    scopes = ()
    uses_nonce = False

    @property
    def client_id(self) -> str:
        return self.settings.naver_client_id

    async def authenticate(self, ctx: LoginContext) -> ProviderIdentity:
        tokens = await self._post_token(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.settings.naver_client_secret.get_secret_value(),
                "code": ctx.code,
                "state": ctx.state,
            }
        )
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str):
            raise ProviderDeniedError(log_detail="naver:no_access_token")
        profile = await self._fetch_profile(access_token)
        return ProviderIdentity(
            provider_user_id=str(profile["id"]),
            email=profile.get("email"),
            # 네이버는 인증된 이메일만 제공한다.
            email_verified=profile.get("email") is not None,
            display_name=profile.get("nickname") or profile.get("name"),
        )

    async def _fetch_profile(self, access_token: str) -> dict[str, Any]:
        # 프로필 조회는 멱등이므로 지수 백오프로 최대 2회 재시도한다 (CLAUDE.md §3.2-5).
        last_exc: Exception | None = None
        for attempt in range(PROFILE_MAX_RETRIES + 1):
            if attempt:
                await asyncio.sleep(PROFILE_BACKOFF_SECONDS * 2 ** (attempt - 1))
            try:
                res = await self.http.get(
                    self.profile_endpoint, headers={"Authorization": f"Bearer {access_token}"}
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if res.status_code >= 500:
                last_exc = None
                continue
            body: dict[str, Any] = res.json()
            if res.status_code >= 400 or body.get("resultcode") != "00":
                raise ProviderDeniedError(log_detail=f"naver:profile:{body.get('resultcode')}")
            response: dict[str, Any] = body["response"]
            return response
        raise ProviderUnavailableError(log_detail="naver:profile") from last_exc
