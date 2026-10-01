import logging
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConsentType,
    LlmTier,
    LogStatus,
    TransformationLog,
    TransformKind,
    User,
    UserConsent,
)
from app.privacy.log_writer import LogEntry, TransformationLogWriter

DRAFT = "민수씨 010-0000-0000으로 연락 주세요"
OUTPUT = {"variants": [{"text": "민수씨, 010-0000-0000으로 연락 부탁드려요"}]}


async def make_user(db: AsyncSession, consent: bool | None) -> uuid.UUID:
    user = User()
    db.add(user)
    await db.flush()
    if consent is not None:
        db.add(
            UserConsent(
                user_id=user.id,
                consent_type=ConsentType.QUALITY_LOG_COLLECTION,
                version="2026-10-01",
                agreed=consent,
            )
        )
    await db.commit()
    return user.id


def entry(user_id: uuid.UUID, status: LogStatus = LogStatus.SUCCESS) -> LogEntry:
    return LogEntry(
        user_id=user_id,
        request_id="req-1",
        kind=TransformKind.TONE_TRANSFORM,
        status=status,
        model_tier=LlmTier.LIGHT,
        model_id="claude-haiku-4-5",
        draft=DRAFT,
        output=OUTPUT,
        emotion_temperature=40,
        input_tokens=10,
    )


@pytest.mark.parametrize("consent", [None, False])
async def test_without_consent_only_metrics_are_stored(
    app: FastAPI, db: AsyncSession, consent: bool | None
) -> None:
    user_id = await make_user(db, consent)
    await TransformationLogWriter(app.state.sessionmaker).write(entry(user_id))
    row = (await db.execute(select(TransformationLog))).scalar_one()
    assert row.masked_draft is None and row.masked_output is None
    assert row.pii_types_detected is None
    assert row.emotion_temperature == 40 and row.input_tokens == 10


async def test_with_consent_text_is_masked(app: FastAPI, db: AsyncSession) -> None:
    user_id = await make_user(db, True)
    await TransformationLogWriter(app.state.sessionmaker).write(entry(user_id))
    row = (await db.execute(select(TransformationLog))).scalar_one()
    assert row.masked_draft == "[NAME_1]씨 [PHONE_1]으로 연락 주세요"
    assert row.masked_output == {
        "variants": [{"text": "[NAME_1]씨, [PHONE_1]으로 연락 부탁드려요"}]
    }
    assert sorted(row.pii_types_detected or []) == ["NAME", "PHONE"]
    assert row.expires_at > row.created_at


async def test_guardrail_blocked_never_stores_text(app: FastAPI, db: AsyncSession) -> None:
    user_id = await make_user(db, True)
    writer = TransformationLogWriter(app.state.sessionmaker)
    await writer.write(entry(user_id, LogStatus.GUARDRAIL_BLOCKED))
    row = (await db.execute(select(TransformationLog))).scalar_one()
    assert row.masked_draft is None


async def test_write_failure_is_swallowed_and_logged_without_content(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    bad = entry(uuid.uuid4())  # 존재하지 않는 user_id → FK 위반
    with caplog.at_level(logging.ERROR):
        await TransformationLogWriter(app.state.sessionmaker).write(bad)
    assert any(r.getMessage() == "transformation_log.write_failed" for r in caplog.records)
    assert "010-0000-0000" not in repr(bad)
