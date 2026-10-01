import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import RefreshInvalidError, RefreshReusedError
from app.core.security import create_access_token, generate_refresh_token, hash_token
from app.db.base import utcnow, uuid7
from app.db.models import RefreshToken

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    user_id: uuid.UUID


class TokenService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _new_refresh_row(
        self,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        device_info: str | None,
    ) -> tuple[RefreshToken, str]:
        raw = generate_refresh_token()
        now = utcnow()
        row = RefreshToken(
            id=uuid7(),
            user_id=user_id,
            token_hash=hash_token(raw),
            family_id=family_id,
            parent_id=parent_id,
            device_info=device_info,
            issued_at=now,
            expires_at=now + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
        )
        self.db.add(row)
        return row, raw

    def issue(self, user_id: uuid.UUID, device_info: str | None = None) -> IssuedTokens:
        """새 로그인 = 새 token family. 호출한 쪽에서 commit한다."""
        _, raw = self._new_refresh_row(user_id, uuid7(), None, device_info)
        return IssuedTokens(create_access_token(user_id, self.settings), raw, user_id)

    async def rotate(self, raw_token: str) -> IssuedTokens:
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw_token))
            .with_for_update()
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise RefreshInvalidError(log_detail="unknown")

        now = utcnow()
        if row.revoked_at is not None:
            if row.revoked_reason != "rotated":
                raise RefreshInvalidError(log_detail=f"revoked:{row.revoked_reason}")
            grace = timedelta(seconds=self.settings.refresh_reuse_grace_seconds)
            if now - _aware(row.revoked_at) > grace:
                await self.revoke_family(row.family_id, "reuse_detected")
                await self.db.commit()
                logger.warning(
                    "security.refresh_reuse",
                    extra={"user_id": str(row.user_id), "family_id": str(row.family_id)},
                )
                raise RefreshReusedError()
            # 동시 요청 경합에서 진 쪽: 재사용으로 보지 않고 같은 부모에서 새 자식을 발급한다.
        elif _aware(row.expires_at) <= now:
            raise RefreshInvalidError(log_detail="expired")
        else:
            row.revoked_at = now
            row.revoked_reason = "rotated"

        _, raw = self._new_refresh_row(row.user_id, row.family_id, row.id, row.device_info)
        await self.db.commit()
        return IssuedTokens(create_access_token(row.user_id, self.settings), raw, row.user_id)

    async def revoke_family(self, family_id: uuid.UUID, reason: str) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoked_reason=reason)
        )

    async def revoke_by_raw(self, raw_token: str, user_id: uuid.UUID, reason: str) -> None:
        row = (
            await self.db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
            )
        ).scalar_one_or_none()
        if row is not None and row.user_id == user_id:
            await self.revoke_family(row.family_id, reason)

    async def revoke_all(self, user_id: uuid.UUID, reason: str) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow(), revoked_reason=reason)
        )


def _aware(value: datetime) -> datetime:
    # SQLite는 tz 정보를 버리므로 UTC로 간주한다. PostgreSQL timestamptz는 그대로다.
    return value if value.tzinfo else value.replace(tzinfo=UTC)
