import enum
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TextArray, utcnow, uuid7
from app.db.models.auth import _pg_enum

JsonDoc = JSON().with_variant(JSONB(), "postgresql")
LOG_RETENTION = timedelta(days=90)


class LlmTier(enum.StrEnum):
    LIGHT = "light"
    HEAVY = "heavy"


class TransformKind(enum.StrEnum):
    TONE_TRANSFORM = "tone_transform"
    TONE_ANALYZE = "tone_analyze"
    REPLY_INTERPRET = "reply_interpret"


class LogStatus(enum.StrEnum):
    SUCCESS = "success"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    LLM_ERROR = "llm_error"
    SCHEMA_INVALID = "schema_invalid"
    REFUSED = "refused"


class ToneOption(Base):
    __tablename__ = "tone_options"
    __table_args__ = (UniqueConstraint("key", "locale", name="uq_tone_key_locale"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(40))
    locale: Mapped[str] = mapped_column(String(10))
    display_name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(200))
    # LLM에 넘기는 페르소나 지침. 정확성을 위해 locale과 무관하게 영어로 쓴다.
    prompt_directive: Mapped[str] = mapped_column(Text)
    default_tier: Mapped[LlmTier] = mapped_column(
        _pg_enum(LlmTier, "llm_tier"), default=LlmTier.LIGHT
    )
    icon: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("name", "locale", "version", name="uq_prompt_version"),
        CheckConstraint("rollout_percent BETWEEN 0 AND 100", name="rollout_percent_range"),
        Index(
            "uq_prompt_active",
            "name",
            "locale",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(10), default="any")
    system_prompt: Mapped[str] = mapped_column(Text)
    user_template: Mapped[str] = mapped_column(Text)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JsonDoc)
    model_tier: Mapped[LlmTier] = mapped_column(_pg_enum(LlmTier, "llm_tier"))
    # temperature 대신 effort로 품질/비용을 조절한다(Sonnet 5.5는 sampling 파라미터를 거부).
    # NULL이면 티어 기본값을 쓴다.
    effort: Mapped[str | None] = mapped_column(String(10))
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    rollout_percent: Mapped[int] = mapped_column(SmallInteger, default=100)
    created_by: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TransformationLog(Base):
    """품질 분석 로그. 원문은 저장하지 않으며 masked_* 컬럼은 동의한 사용자만 채운다."""

    __tablename__ = "transformation_logs"
    __table_args__ = (
        CheckConstraint("emotion_temperature BETWEEN 0 AND 100", name="emotion_temperature_range"),
        Index("ix_tlogs_created", "created_at"),
        Index("ix_tlogs_expires", "expires_at"),
        Index("ix_tlogs_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    request_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[TransformKind] = mapped_column(_pg_enum(TransformKind, "transform_kind"))
    tone_option_key: Mapped[str | None] = mapped_column(String(40))
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prompt_templates.id"))
    model_tier: Mapped[LlmTier] = mapped_column(_pg_enum(LlmTier, "llm_tier"))
    model_id: Mapped[str] = mapped_column(String(60))
    source_lang: Mapped[str | None] = mapped_column(String(10))
    target_lang: Mapped[str | None] = mapped_column(String(10))
    masked_context: Mapped[str | None] = mapped_column(Text)
    masked_draft: Mapped[str | None] = mapped_column(Text)
    masked_output: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc)
    pii_types_detected: Mapped[list[str] | None] = mapped_column(TextArray)
    emotion_temperature: Mapped[int | None] = mapped_column(SmallInteger)
    red_flag_count: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[LogStatus] = mapped_column(_pg_enum(LogStatus, "log_status"))
    guardrail_score: Mapped[float | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cached_tokens: Mapped[int | None]
    ttft_ms: Mapped[int | None]
    latency_ms: Mapped[int | None]
    selected_variant: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(default=lambda: utcnow() + LOG_RETENTION)
