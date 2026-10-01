"""transformation_logs의 유일한 적재 경로 (CLAUDE.md §4.2).

동의 확인과 PII 마스킹을 여기서만 한다. 다른 코드는 TransformationLog를 직접 만들지 않는다.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    ConsentType,
    LlmTier,
    LogStatus,
    TransformationLog,
    TransformKind,
    UserConsent,
)
from app.privacy.pii import MaskResult, mask

logger = logging.getLogger(__name__)


@dataclass
class LogEntry:
    user_id: uuid.UUID | None
    request_id: str
    kind: TransformKind
    status: LogStatus
    model_tier: LlmTier
    model_id: str
    prompt_template_id: uuid.UUID | None = None
    tone_option_key: str | None = None
    source_lang: str | None = None
    target_lang: str | None = None
    # 원문. 동의한 경우에만 마스킹해서 저장하고, 그렇지 않으면 버린다.
    context: str | None = None
    draft: str | None = None
    output: dict[str, Any] | None = field(default=None, repr=False)
    emotion_temperature: int | None = None
    red_flag_count: int | None = None
    guardrail_score: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    ttft_ms: int | None = None
    latency_ms: int | None = None

    def __repr__(self) -> str:  # 원문이 실수로 로그에 찍히지 않게 한다.
        return f"LogEntry(request_id={self.request_id!r}, kind={self.kind}, status={self.status})"


def _mask_json(value: Any, result: MaskResult) -> Any:
    if isinstance(value, str):
        return mask(value, result).text
    if isinstance(value, list):
        return [_mask_json(v, result) for v in value]
    if isinstance(value, dict):
        return {k: _mask_json(v, result) for k, v in value.items()}
    return value


class TransformationLogWriter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def _consented(self, db: AsyncSession, user_id: uuid.UUID) -> bool:
        row = (
            await db.execute(
                select(UserConsent.agreed)
                .where(
                    UserConsent.user_id == user_id,
                    UserConsent.consent_type == ConsentType.QUALITY_LOG_COLLECTION,
                )
                .order_by(UserConsent.agreed_at.desc(), UserConsent.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return bool(row)

    async def write(self, entry: LogEntry) -> None:
        """응답 경로 밖(BackgroundTask)에서 호출한다. 실패해도 사용자 요청에는 영향이 없다."""
        try:
            async with self.sessionmaker() as db:
                keep_text = (
                    entry.user_id is not None
                    and entry.status is not LogStatus.GUARDRAIL_BLOCKED
                    and await self._consented(db, entry.user_id)
                )
                masked = MaskResult(text="")
                masked_context = masked_draft = None
                masked_output = None
                if keep_text:
                    masked_context = mask(entry.context, masked).text if entry.context else None
                    masked_draft = mask(entry.draft, masked).text if entry.draft else None
                    masked_output = _mask_json(entry.output, masked) if entry.output else None
                db.add(
                    TransformationLog(
                        user_id=entry.user_id,
                        request_id=entry.request_id,
                        kind=entry.kind,
                        tone_option_key=entry.tone_option_key,
                        prompt_template_id=entry.prompt_template_id,
                        model_tier=entry.model_tier,
                        model_id=entry.model_id,
                        source_lang=entry.source_lang,
                        target_lang=entry.target_lang,
                        masked_context=masked_context,
                        masked_draft=masked_draft,
                        masked_output=masked_output,
                        pii_types_detected=sorted(masked.types) or None,
                        emotion_temperature=entry.emotion_temperature,
                        red_flag_count=entry.red_flag_count,
                        status=entry.status,
                        guardrail_score=entry.guardrail_score,
                        input_tokens=entry.input_tokens,
                        output_tokens=entry.output_tokens,
                        cached_tokens=entry.cached_tokens,
                        ttft_ms=entry.ttft_ms,
                        latency_ms=entry.latency_ms,
                    )
                )
                await db.commit()
        except Exception:
            logger.exception("transformation_log.write_failed")
