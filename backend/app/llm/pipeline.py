"""Guardrail과 본 LLM 호출을 동시에 돌리는 공통 파이프라인 (ARCHITECTURE §5.1).

가드레일 분류(경량 모델)를 기다린 뒤 본 호출을 시작하면 첫 응답이 그만큼 늦어진다.
그래서 둘을 동시에 시작하고, 가드레일이 통과하기 전까지는 본 호출의 텍스트를 내보내지 않고
쌓아 둔다. 차단되면 본 호출을 즉시 끊는다.
"""

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.core.errors import (
    InputRejectedError,
    LlmOutputInvalidError,
    LlmRefusedError,
    LlmUpstreamError,
)
from app.db.models import LlmTier, LogStatus
from app.llm.client import LlmCall, LlmClient, StreamDone, TextDelta, check_stop_reason
from app.llm.guardrails import GuardrailResult


@dataclass
class StreamStats:
    """스트림이 끝난 뒤 로그·응답에 쓸 값."""

    started_at: float = field(default_factory=time.perf_counter)
    ttft_ms: int | None = None
    latency_ms: int | None = None
    done: StreamDone | None = None
    guard: GuardrailResult | None = None


async def guarded_stream(
    llm: LlmClient,
    tier: LlmTier,
    call: LlmCall,
    guard: Coroutine[Any, Any, GuardrailResult],
    stats: StreamStats,
) -> AsyncIterator[str]:
    """가드레일을 통과한 텍스트 조각만 내보낸다. 차단되면 InputRejectedError가 올라간다."""
    guard_task = asyncio.create_task(guard)
    buffer: list[str] = []

    def emit(text: str) -> str:
        if stats.ttft_ms is None:
            stats.ttft_ms = int((time.perf_counter() - stats.started_at) * 1000)
        return text

    try:
        async with contextlib.aclosing(llm.stream(tier, call)) as events:
            async for event in events:
                if isinstance(event, StreamDone):
                    stats.done = event
                elif isinstance(event, TextDelta):
                    if not guard_task.done():
                        buffer.append(event.text)
                        continue
                    stats.guard = guard_task.result()  # 차단이면 여기서 예외
                    for text in buffer:
                        yield emit(text)
                    buffer.clear()
                    yield emit(event.text)
        stats.guard = await guard_task
        for text in buffer:
            yield emit(text)
    finally:
        if not guard_task.done():
            guard_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await guard_task
        stats.latency_ms = int((time.perf_counter() - stats.started_at) * 1000)

    if stats.done is None:
        raise LlmUpstreamError(log_detail="no_final_message")
    check_stop_reason(stats.done)


def status_for(exc: Exception) -> LogStatus:
    """예외를 transformation_logs.status로 바꾼다."""
    if isinstance(exc, InputRejectedError):
        return LogStatus.GUARDRAIL_BLOCKED
    if isinstance(exc, LlmRefusedError):
        return LogStatus.REFUSED
    if isinstance(exc, LlmOutputInvalidError | ValidationError):
        return LogStatus.SCHEMA_INVALID
    return LogStatus.LLM_ERROR
