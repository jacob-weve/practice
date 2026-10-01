import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TextArray, utcnow, uuid7


class SocialProvider(enum.StrEnum):
    KAKAO = "kakao"
    GOOGLE = "google"
    NAVER = "naver"
    APPLE = "apple"


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_CONSENT = "pending_consent"


class ConsentType(enum.StrEnum):
    TERMS_OF_SERVICE = "terms_of_service"
    PRIVACY_POLICY = "privacy_policy"
    AGE_OVER_14 = "age_over_14"
    MARKETING = "marketing"
    QUALITY_LOG_COLLECTION = "quality_log_collection"


REQUIRED_CONSENTS = (
    ConsentType.TERMS_OF_SERVICE,
    ConsentType.PRIVACY_POLICY,
    ConsentType.AGE_OVER_14,
)


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    display_name: Mapped[str | None] = mapped_column(String(50))
    primary_email: Mapped[str | None] = mapped_column(String(320))
    ui_locale: Mapped[str] = mapped_column(String(10), default="ko", server_default="ko")
    default_target_lang: Mapped[str] = mapped_column(String(10), default="ko", server_default="ko")
    plan: Mapped[str] = mapped_column(String(20), default="free", server_default="free")
    status: Mapped[UserStatus] = mapped_column(
        _pg_enum(UserStatus, "user_status"), default=UserStatus.PENDING_CONSENT
    )
    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("social_provider", "provider_user_id", name="uq_provider_identity"),
        UniqueConstraint("user_id", "social_provider", name="uq_user_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    social_provider: Mapped[SocialProvider] = mapped_column(
        _pg_enum(SocialProvider, "social_provider")
    )
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_private_email: Mapped[bool] = mapped_column(Boolean, default=False)
    # 탈퇴 시 revoke용 제공자 refresh_token. AES-256-GCM 암호문만 저장한다.
    provider_refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    scopes: Mapped[list[str] | None] = mapped_column(TextArray)
    linked_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(back_populates="social_accounts")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_family", "family_id"),
        Index(
            "ix_refresh_tokens_user_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    device_info: Mapped[str | None] = mapped_column(String(200))
    issued_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(String(30))


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (Index("ix_user_consents_latest", "user_id", "consent_type", "agreed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    consent_type: Mapped[ConsentType] = mapped_column(_pg_enum(ConsentType, "consent_type"))
    version: Mapped[str] = mapped_column(String(20))
    agreed: Mapped[bool] = mapped_column(Boolean)
    agreed_at: Mapped[datetime] = mapped_column(default=utcnow)
