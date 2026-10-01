import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.service import AuthService
from app.core.deps import DbDep, HttpClientDep, RedisDep, SettingsDep
from app.core.errors import (
    AccountSuspendedError,
    ConsentRequiredError,
    TokenInvalidError,
)
from app.core.rate_limit import enforce_fixed_window
from app.core.security import decode_access_token
from app.db.models import User, UserStatus

AUTH_RATE_LIMIT_PER_MINUTE = 20


def get_auth_service(
    db: DbDep, redis: RedisDep, http: HttpClientDep, settings: SettingsDep
) -> AuthService:
    return AuthService(db, redis, http, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise TokenInvalidError(log_detail="missing_bearer")
    return token.strip()


async def get_current_user(request: Request, db: DbDep, settings: SettingsDep) -> User:
    """동의 대기(pending_consent) 사용자도 통과시킨다. 동의 제출·프로필·로그아웃 전용."""
    claims = decode_access_token(_bearer_token(request), settings)
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise TokenInvalidError(log_detail="bad_sub") from exc
    user = (
        await db.execute(
            select(User).where(User.id == user_id).options(selectinload(User.social_accounts))
        )
    ).scalar_one_or_none()
    if user is None:
        raise TokenInvalidError(log_detail="user_not_found")
    if user.status is UserStatus.SUSPENDED:
        raise AccountSuspendedError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_active_user(user: CurrentUser) -> User:
    if user.status is not UserStatus.ACTIVE:
        raise ConsentRequiredError()
    return user


ActiveUser = Annotated[User, Depends(get_active_user)]


async def auth_rate_limit(request: Request, redis: RedisDep) -> None:
    client_ip = request.client.host if request.client else "unknown"
    await enforce_fixed_window(redis, f"auth:{client_ip}", AUTH_RATE_LIMIT_PER_MINUTE, 60)
