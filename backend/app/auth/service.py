import base64
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.providers import (
    AppleProvider,
    LoginContext,
    OAuthProvider,
    ProviderIdentity,
    get_provider,
)
from app.auth.schemas import (
    AppleUser,
    ConsentItem,
    RequiredConsent,
    SocialLoginRequest,
    UserProfile,
)
from app.auth.state_store import AppleHandoff, OAuthStateStore, PendingAuthorization
from app.auth.tokens import IssuedTokens, TokenService
from app.core.config import Settings
from app.core.errors import (
    AccountLinkConflictError,
    AccountSuspendedError,
    AppError,
    InvalidRedirectUriError,
    InvalidStateError,
    PKCEMismatchError,
)
from app.core.security import constant_time_equals, encrypt_secret, generate_opaque, pkce_s256
from app.db.base import utcnow, uuid7
from app.db.models import (
    REQUIRED_CONSENTS,
    ConsentType,
    SocialAccount,
    SocialProvider,
    User,
    UserConsent,
    UserStatus,
)

logger = logging.getLogger(__name__)

REVOKE_QUEUE_KEY = "oauth:revoke_queue"
CONSENT_URLS = {
    ConsentType.TERMS_OF_SERVICE: "/terms",
    ConsentType.PRIVACY_POLICY: "/privacy",
}


@dataclass(frozen=True)
class LoginResult:
    tokens: IssuedTokens
    user: User
    is_new_user: bool


class AuthService:
    def __init__(
        self, db: AsyncSession, redis: Redis, http: httpx.AsyncClient, settings: Settings
    ) -> None:
        self.db = db
        self.redis = redis
        self.http = http
        self.settings = settings
        self.states = OAuthStateStore(redis, settings.oauth_state_ttl_seconds)
        self.tokens = TokenService(db, settings)

    def _provider(self, provider: SocialProvider) -> OAuthProvider:
        return get_provider(provider, self.settings, self.http, self.redis)

    def _check_redirect_uri(self, redirect_uri: str) -> None:
        if redirect_uri not in self.settings.oauth_redirect_uris:
            raise InvalidRedirectUriError()

    # ---------------------------------------------------------------- authorize
    async def authorize(
        self, provider: SocialProvider, code_challenge: str, redirect_uri: str
    ) -> tuple[str, str]:
        self._check_redirect_uri(redirect_uri)
        state = generate_opaque(24)
        nonce = generate_opaque(24)
        await self.states.save(
            state,
            PendingAuthorization(
                provider=provider.value,
                nonce=nonce,
                code_challenge=code_challenge,
                redirect_uri=redirect_uri,
            ),
        )
        url = self._provider(provider).build_authorize_url(
            state=state, nonce=nonce, code_challenge=code_challenge, redirect_uri=redirect_uri
        )
        return url, state

    async def save_apple_handoff(self, code: str, state: str, user_json: str | None) -> str:
        user: dict[str, Any] | None = None
        if user_json:
            try:
                parsed = json.loads(user_json)
                user = parsed if isinstance(parsed, dict) else None
            except ValueError:
                user = None
        return await self.states.save_apple_handoff(AppleHandoff(code, state, user))

    # -------------------------------------------------------------------- login
    async def _identify(
        self, provider: SocialProvider, req: SocialLoginRequest
    ) -> tuple[ProviderIdentity, AppleUser | None]:
        apple_user = req.apple_user
        code, state = req.code, req.state
        if req.handoff is not None:
            if provider is not SocialProvider.APPLE:
                raise InvalidStateError(log_detail="handoff_non_apple")
            handoff = await self.states.consume_apple_handoff(req.handoff)
            if handoff is None:
                raise InvalidStateError(log_detail="handoff_missing")
            code, state = handoff.code, handoff.state
            if apple_user is None and handoff.user:
                apple_user = AppleUser.model_validate(handoff.user)
        assert code is not None and state is not None  # noqa: S101 (스키마 검증으로 보장)

        pending = await self.states.consume(state)
        if pending is None or pending.provider != provider.value:
            raise InvalidStateError(log_detail="state_missing_or_provider_mismatch")
        if not constant_time_equals(pending.redirect_uri, req.redirect_uri):
            raise InvalidStateError(log_detail="redirect_uri_mismatch")
        # 제공자의 PKCE 지원 여부와 무관하게 인가를 시작한 클라이언트인지 서버가 직접 확인한다.
        if not constant_time_equals(pkce_s256(req.code_verifier), pending.code_challenge):
            raise PKCEMismatchError()

        identity = await self._provider(provider).authenticate(
            LoginContext(
                code=code,
                redirect_uri=req.redirect_uri,
                code_verifier=req.code_verifier,
                nonce=pending.nonce,
                state=state,
            )
        )
        return identity, apple_user

    async def login(self, provider: SocialProvider, req: SocialLoginRequest) -> LoginResult:
        identity, apple_user = await self._identify(provider, req)
        account = await self._find_account(provider, identity.provider_user_id)
        is_new_user = account is None

        if account is None:
            try:
                user = self._create_user(provider, identity, apple_user)
                await self.db.flush()
            except IntegrityError:
                # 같은 계정으로 동시에 첫 로그인한 경우: 먼저 커밋된 사용자를 쓴다.
                await self.db.rollback()
                account = await self._find_account(provider, identity.provider_user_id)
                if account is None:
                    raise
                user = account.user
                is_new_user = False
        else:
            user = account.user
            self._refresh_account(account, identity, apple_user)

        if user.status is UserStatus.SUSPENDED:
            raise AccountSuspendedError()

        self._record_consents(user.id, req.consents)
        await self.db.flush()
        await self._sync_status(user)
        user.last_login_at = utcnow()
        tokens = self.tokens.issue(user.id, req.device_info)
        await self.db.commit()
        logger.info(
            "auth.login",
            extra={"user_id": str(user.id), "provider": provider.value, "new": is_new_user},
        )
        return LoginResult(tokens, await self._load_user(user.id), is_new_user)

    async def link(self, user: User, provider: SocialProvider, req: SocialLoginRequest) -> User:
        identity, apple_user = await self._identify(provider, req)
        existing = await self._find_account(provider, identity.provider_user_id)
        if existing is not None:
            if existing.user_id != user.id:
                raise AccountLinkConflictError()
            return await self._load_user(user.id)
        if any(a.social_provider is provider for a in user.social_accounts):
            raise AccountLinkConflictError(log_detail="provider_already_linked")
        self.db.add(self._new_account(user.id, provider, identity))
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise AccountLinkConflictError(log_detail="race") from exc
        return await self._load_user(user.id)

    # ----------------------------------------------------------------- consents
    async def submit_consents(self, user: User, consents: list[ConsentItem]) -> User:
        self._record_consents(user.id, consents)
        await self.db.flush()
        await self._sync_status(user)
        await self.db.commit()
        return await self._load_user(user.id)

    def _record_consents(self, user_id: uuid.UUID, consents: list[ConsentItem]) -> None:
        now = utcnow()
        for item in consents:
            self.db.add(
                UserConsent(
                    user_id=user_id,
                    consent_type=item.type,
                    version=item.version,
                    agreed=item.agreed,
                    agreed_at=now,
                )
            )

    async def latest_consents(self, user_id: uuid.UUID) -> dict[ConsentType, UserConsent]:
        rows = (
            await self.db.execute(
                select(UserConsent)
                .where(UserConsent.user_id == user_id)
                .order_by(UserConsent.agreed_at, UserConsent.id)
            )
        ).scalars()
        latest: dict[ConsentType, UserConsent] = {}
        for row in rows:
            latest[row.consent_type] = row
        return latest

    async def missing_required_consents(self, user_id: uuid.UUID) -> list[RequiredConsent]:
        latest = await self.latest_consents(user_id)
        missing = []
        for consent_type in REQUIRED_CONSENTS:
            row = latest.get(consent_type)
            if row is None or not row.agreed or row.version != self.settings.consent_version:
                path = CONSENT_URLS.get(consent_type)
                missing.append(
                    RequiredConsent(
                        type=consent_type,
                        version=self.settings.consent_version,
                        url=f"{self.settings.web_base_url}{path}" if path else None,
                    )
                )
        return missing

    async def _sync_status(self, user: User) -> None:
        if user.status is UserStatus.SUSPENDED:
            return
        missing = await self.missing_required_consents(user.id)
        user.status = UserStatus.PENDING_CONSENT if missing else UserStatus.ACTIVE

    # --------------------------------------------------------------- withdrawal
    async def delete_user(self, user: User) -> None:
        accounts = list(user.social_accounts)
        for account in accounts:
            await self._revoke_or_enqueue(account)
        # 제공자 해제 결과와 무관하게 사용자 데이터는 지운다 (CLAUDE.md §3.2-11).
        await self.db.execute(delete(User).where(User.id == user.id))
        await self.db.commit()
        logger.info("auth.user_deleted", extra={"user_id": str(user.id)})

    async def _revoke_or_enqueue(self, account: SocialAccount) -> None:
        try:
            await self._provider(account.social_provider).revoke(account)
        except AppError:
            payload = {
                "provider": account.social_provider.value,
                "provider_user_id": account.provider_user_id,
                "token_enc": base64.b64encode(account.provider_refresh_token_enc).decode()
                if account.provider_refresh_token_enc
                else None,
            }
            await self.redis.rpush(REVOKE_QUEUE_KEY, json.dumps(payload))
            logger.warning(
                "auth.revoke_enqueued",
                extra={"user_id": str(account.user_id), "provider": payload["provider"]},
            )

    async def handle_apple_notification(self, payload_jwt: str) -> None:
        apple = self._provider(SocialProvider.APPLE)
        assert isinstance(apple, AppleProvider)  # noqa: S101
        claims = await apple.verify(payload_jwt, nonce=None, required_claims=("iss", "aud", "iat"))
        raw_events = claims.get("events")
        events: dict[str, Any] = (
            json.loads(raw_events) if isinstance(raw_events, str) else raw_events or {}
        )
        event_type = events.get("type")
        sub = events.get("sub")
        if not isinstance(sub, str):
            return
        account = await self._find_account(SocialProvider.APPLE, sub)
        if account is None:
            return
        if event_type in ("consent-revoked", "account-delete"):
            user = account.user
            await self.db.delete(account)
            await self.db.flush()
            remaining = await self.db.scalar(
                select(SocialAccount.id).where(SocialAccount.user_id == user.id).limit(1)
            )
            if remaining is None:
                await self.db.execute(delete(User).where(User.id == user.id))
            else:
                await self.tokens.revoke_all(user.id, "provider_revoked")
            await self.db.commit()
        logger.info("auth.apple_notification", extra={"event_type": event_type})

    # ------------------------------------------------------------------ helpers
    async def _find_account(
        self, provider: SocialProvider, provider_user_id: str
    ) -> SocialAccount | None:
        stmt = (
            select(SocialAccount)
            .where(
                SocialAccount.social_provider == provider,
                SocialAccount.provider_user_id == provider_user_id,
            )
            .options(selectinload(SocialAccount.user).selectinload(User.social_accounts))
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _load_user(self, user_id: uuid.UUID) -> User:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.social_accounts))
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one()

    def _new_account(
        self, user_id: uuid.UUID, provider: SocialProvider, identity: ProviderIdentity
    ) -> SocialAccount:
        return SocialAccount(
            user_id=user_id,
            social_provider=provider,
            provider_user_id=identity.provider_user_id,
            email=identity.email,
            email_verified=identity.email_verified,
            is_private_email=identity.is_private_email,
            provider_refresh_token_enc=encrypt_secret(identity.refresh_token, self.settings)
            if identity.refresh_token
            else None,
            scopes=identity.scopes or None,
            last_used_at=utcnow(),
        )

    def _create_user(
        self, provider: SocialProvider, identity: ProviderIdentity, apple_user: AppleUser | None
    ) -> User:
        # 이메일이 같은 기존 사용자가 있어도 자동 병합하지 않는다 (CLAUDE.md §3.2-8).
        user = User(
            id=uuid7(),
            display_name=_display_name(identity, apple_user),
            primary_email=identity.email,
            ui_locale=self.settings.default_locale,
            status=UserStatus.PENDING_CONSENT,
        )
        self.db.add(user)
        user.social_accounts.append(self._new_account(user.id, provider, identity))
        return user

    def _refresh_account(
        self, account: SocialAccount, identity: ProviderIdentity, apple_user: AppleUser | None
    ) -> None:
        account.last_used_at = utcnow()
        if identity.email:
            account.email = identity.email
            account.email_verified = identity.email_verified
            account.is_private_email = identity.is_private_email
        if identity.refresh_token:
            account.provider_refresh_token_enc = encrypt_secret(
                identity.refresh_token, self.settings
            )
        user = account.user
        if user.display_name is None:
            user.display_name = _display_name(identity, apple_user)
        if user.primary_email is None and identity.email:
            user.primary_email = identity.email


def _display_name(identity: ProviderIdentity, apple_user: AppleUser | None) -> str | None:
    if identity.display_name:
        return identity.display_name[:50]
    if apple_user and apple_user.name:
        parts = [apple_user.name.firstName, apple_user.name.lastName]
        joined = " ".join(p for p in parts if p)
        return joined[:50] or None
    return None


def to_profile(user: User) -> UserProfile:
    primary = next(
        (a for a in user.social_accounts if a.email and a.email == user.primary_email), None
    )
    return UserProfile(
        id=user.id,
        display_name=user.display_name,
        email=user.primary_email,
        is_private_email=bool(primary and primary.is_private_email),
        status=user.status,
        ui_locale=user.ui_locale,
        default_target_lang=user.default_target_lang,
        plan=user.plan,
        linked_providers=sorted(
            (a.social_provider for a in user.social_accounts), key=lambda p: p.value
        ),
    )
