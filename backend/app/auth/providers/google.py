from app.auth.providers.base import LoginContext, OAuthProvider, ProviderIdentity
from app.auth.providers.oidc import JwksCache, as_bool, verify_id_token
from app.core.errors import IdTokenInvalidError
from app.db.models import SocialProvider


class GoogleProvider(OAuthProvider):
    name = SocialProvider.GOOGLE
    authorize_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"  # noqa: S105 (URL)
    jwks_uri = "https://www.googleapis.com/oauth2/v3/certs"
    issuers = ("https://accounts.google.com", "accounts.google.com")
    scopes = ("openid", "email", "profile")
    supports_pkce = True

    @property
    def client_id(self) -> str:
        return self.settings.google_client_id

    def extra_authorize_params(self) -> dict[str, str]:
        return {"prompt": "select_account"}

    async def authenticate(self, ctx: LoginContext) -> ProviderIdentity:
        tokens = await self._post_token(
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.settings.google_client_secret.get_secret_value(),
                "redirect_uri": ctx.redirect_uri,
                "code": ctx.code,
                "code_verifier": ctx.code_verifier,
            }
        )
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise IdTokenInvalidError(log_detail="google:no_id_token")
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
            email_verified=as_bool(claims.get("email_verified")),
            display_name=claims.get("name"),
            scopes=str(tokens.get("scope", "")).split(),
        )
