import time
from typing import Any

import httpx
import jwt

from app.auth.providers.base import LoginContext, OAuthProvider, ProviderIdentity
from app.auth.providers.oidc import JwksCache, as_bool, verify_id_token
from app.core.errors import IdTokenInvalidError, ProviderUnavailableError
from app.core.security import decrypt_secret
from app.db.models import SocialAccount, SocialProvider

APPLE_AUDIENCE = "https://appleid.apple.com"
CLIENT_SECRET_TTL_SECONDS = 3600
PRIVATE_RELAY_DOMAIN = "privaterelay.appleid.com"


class AppleProvider(OAuthProvider):
    name = SocialProvider.APPLE
    authorize_endpoint = "https://appleid.apple.com/auth/authorize"
    token_endpoint = "https://appleid.apple.com/auth/token"  # noqa: S105 (URL)
    revoke_endpoint = "https://appleid.apple.com/auth/revoke"
    jwks_uri = "https://appleid.apple.com/auth/keys"
    issuers = (APPLE_AUDIENCE,)
    scopes = ("name", "email")

    _cached_secret: tuple[str, float] | None = None

    @property
    def client_id(self) -> str:
        return self.settings.apple_client_id

    def extra_authorize_params(self) -> dict[str, str]:
        # name/email scope를 요청하면 애플은 form_post 응답만 허용한다.
        return {"response_mode": "form_post"}

    def client_secret(self) -> str:
        """애플 client_secret은 .p8 키로 서명한 ES256 JWT다. 만료 5분 전까지 재사용한다."""
        now = time.time()
        cached = AppleProvider._cached_secret
        if cached and cached[1] - 300 > now:
            return cached[0]
        exp = now + CLIENT_SECRET_TTL_SECONDS
        token = jwt.encode(
            {
                "iss": self.settings.apple_team_id,
                "iat": int(now),
                "exp": int(exp),
                "aud": APPLE_AUDIENCE,
                "sub": self.client_id,
            },
            self.settings.apple_private_key.get_secret_value(),
            algorithm="ES256",
            headers={"kid": self.settings.apple_key_id},
        )
        AppleProvider._cached_secret = (token, exp)
        return token

    async def authenticate(self, ctx: LoginContext) -> ProviderIdentity:
        tokens = await self._post_token(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret(),
                "redirect_uri": ctx.redirect_uri,
                "code": ctx.code,
            }
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise IdTokenInvalidError(log_detail="apple:no_id_token")
        claims = await self.verify(id_token, nonce=ctx.nonce)
        email: str | None = claims.get("email")
        return ProviderIdentity(
            provider_user_id=str(claims["sub"]),
            email=email,
            email_verified=as_bool(claims.get("email_verified")),
            is_private_email=as_bool(claims.get("is_private_email"))
            or bool(email and email.endswith("@" + PRIVATE_RELAY_DOMAIN)),
            refresh_token=tokens.get("refresh_token"),
        )

    async def verify(
        self,
        token: str,
        *,
        nonce: str | None,
        required_claims: tuple[str, ...] = ("iss", "aud", "exp", "iat", "sub"),
    ) -> dict[str, Any]:
        return await verify_id_token(
            token,
            provider=self.name,
            jwks=JwksCache(self.http, self.redis, self.settings.jwks_cache_ttl_seconds),
            jwks_uri=self.jwks_uri,
            issuers=self.issuers,
            audience=self.client_id,
            nonce=nonce,
            required_claims=required_claims,
        )

    async def revoke(self, account: SocialAccount) -> None:
        if not account.provider_refresh_token_enc:
            return
        refresh_token = decrypt_secret(account.provider_refresh_token_enc, self.settings)
        try:
            res = await self.http.post(
                self.revoke_endpoint,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret(),
                    "token": refresh_token,
                    "token_type_hint": "refresh_token",
                },
            )
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(log_detail="apple:revoke") from exc
