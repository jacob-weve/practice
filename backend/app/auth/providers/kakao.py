import httpx

from app.auth.providers.base import LoginContext, OAuthProvider, ProviderIdentity
from app.auth.providers.oidc import JwksCache, as_bool, verify_id_token
from app.core.errors import IdTokenInvalidError, ProviderUnavailableError
from app.db.models import SocialAccount, SocialProvider


class KakaoProvider(OAuthProvider):
    name = SocialProvider.KAKAO
    authorize_endpoint = "https://kauth.kakao.com/oauth/authorize"
    token_endpoint = "https://kauth.kakao.com/oauth/token"  # noqa: S105 (URL)
    jwks_uri = "https://kauth.kakao.com/.well-known/jwks.json"
    unlink_endpoint = "https://kapi.kakao.com/v1/user/unlink"
    issuers = ("https://kauth.kakao.com",)
    scopes = ("openid", "profile_nickname", "account_email")

    @property
    def client_id(self) -> str:
        return self.settings.kakao_client_id

    async def authenticate(self, ctx: LoginContext) -> ProviderIdentity:
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": ctx.redirect_uri,
            "code": ctx.code,
        }
        secret = self.settings.kakao_client_secret.get_secret_value()
        if secret:
            data["client_secret"] = secret
        tokens = await self._post_token(data)
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise IdTokenInvalidError(log_detail="kakao:no_id_token")
        claims = await verify_id_token(
            id_token,
            provider=self.name,
            jwks=JwksCache(self.http, self.redis, self.settings.jwks_cache_ttl_seconds),
            jwks_uri=self.jwks_uri,
            issuers=self.issuers,
            audience=self.client_id,
            nonce=ctx.nonce,
        )
        return ProviderIdentity(
            provider_user_id=str(claims["sub"]),
            email=claims.get("email"),
            # 카카오 OIDC id_token의 email은 인증된 이메일만 내려온다.
            email_verified=as_bool(claims.get("email_verified", claims.get("email") is not None)),
            display_name=claims.get("nickname"),
            scopes=str(tokens.get("scope", "")).split(),
        )

    async def revoke(self, account: SocialAccount) -> None:
        admin_key = self.settings.kakao_admin_key.get_secret_value()
        if not admin_key:
            return
        try:
            res = await self.http.post(
                self.unlink_endpoint,
                headers={"Authorization": f"KakaoAK {admin_key}"},
                data={"target_id_type": "user_id", "target_id": account.provider_user_id},
            )
            res.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(log_detail="kakao:unlink") from exc
