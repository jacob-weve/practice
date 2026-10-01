"""LLM 호출 계층. 도메인 코드는 SDK를 직접 쓰지 않고 이 모듈만 쓴다 (CLAUDE.md §5)."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
from pydantic import BaseModel, ValidationError
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import (
    LlmBusyError,
    LlmOutputInvalidError,
    LlmRefusedError,
    LlmUpstreamError,
)
from app.db.models import LlmTier

logger = logging.getLogger(__name__)

SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
INFLIGHT_TTL_SECONDS = 120


@dataclass(frozen=True)
class LlmCall:
    system: str
    user: str
    output_schema: dict[str, Any]
    max_tokens: int
    effort: str | None = None  # 템플릿 지정값. None이면 모델별 기본값


@dataclass(frozen=True)
class Started:
    model: str


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StreamDone:
    model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int


StreamEvent = Started | TextDelta | StreamDone


class TransientProviderError(Exception):
    """다른 모델로 재시도해도 되는 제공사 오류(연결, 타임아웃, 429, 5xx)."""


class LlmProvider(Protocol):
    def stream(
        self, model: str, call: LlmCall, *, effort: str | None, server_fallback: bool
    ) -> AsyncGenerator[StreamEvent]: ...


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        api_key = settings.anthropic_api_key.get_secret_value() or None
        # 재시도는 같은 티어 대체 모델로 직접 하므로 SDK 재시도는 1회로 줄인다.
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=1, timeout=settings.llm_request_timeout_seconds
        )

    async def stream(
        self, model: str, call: LlmCall, *, effort: str | None, server_fallback: bool
    ) -> AsyncGenerator[StreamEvent]:
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": call.output_schema}
        }
        if effort:
            output_config["effort"] = effort
        extra: dict[str, Any] = {}
        if server_fallback:
            extra = {"betas": [SERVER_FALLBACK_BETA], "fallbacks": "default"}
        try:
            async with self.client.beta.messages.stream(
                model=model,
                max_tokens=call.max_tokens,
                # 시스템 지침은 요청마다 같으므로 캐시한다. 변하는 값은 user 쪽에만 둔다.
                system=[
                    {"type": "text", "text": call.system, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": call.user}],
                output_config=output_config,  # type: ignore[arg-type]
                **extra,
            ) as stream:
                yield Started(model)
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                final = await stream.get_final_message()
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as exc:
            raise TransientProviderError(type(exc).__name__) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientProviderError(f"status:{exc.status_code}") from exc
            raise LlmUpstreamError(log_detail=f"{model}:status:{exc.status_code}") from exc
        usage = final.usage
        yield StreamDone(
            model=final.model,
            stop_reason=final.stop_reason,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cache_read_input_tokens or 0,
        )


@dataclass
class CircuitBreaker:
    """프로세스 단위 서킷 브레이커. 연속 실패가 임계값을 넘으면 일정 시간 그 모델을 건너뛴다."""

    threshold: int
    open_seconds: float
    clock: Callable[[], float] = time.monotonic
    _failures: dict[str, int] = field(default_factory=dict)
    _opened_at: dict[str, float] = field(default_factory=dict)

    def is_open(self, model: str) -> bool:
        opened = self._opened_at.get(model)
        if opened is None:
            return False
        if self.clock() - opened >= self.open_seconds:
            # half-open: 다음 호출 한 번을 허용해 본다.
            del self._opened_at[model]
            self._failures[model] = self.threshold - 1
            return False
        return True

    def record_success(self, model: str) -> None:
        self._failures.pop(model, None)
        self._opened_at.pop(model, None)

    def record_failure(self, model: str) -> None:
        count = self._failures.get(model, 0) + 1
        self._failures[model] = count
        if count >= self.threshold:
            self._opened_at[model] = self.clock()


@dataclass(frozen=True)
class CallResult:
    text: str
    done: StreamDone
    ttft_ms: int | None
    latency_ms: int


class LlmClient:
    def __init__(
        self,
        provider: LlmProvider,
        settings: Settings,
        redis: Redis,
        breaker: CircuitBreaker,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.redis = redis
        self.breaker = breaker

    def candidates(self, tier: LlmTier) -> list[str]:
        s = self.settings
        primary, fallback = (
            (s.llm_model_heavy, s.llm_model_heavy_fallback)
            if tier is LlmTier.HEAVY
            else (s.llm_model_light, s.llm_model_light_fallback)
        )
        models = [m for m in (primary, fallback) if m]
        available = [m for m in dict.fromkeys(models) if not self.breaker.is_open(m)]
        # 모두 열려 있으면 기본 모델이라도 시도한다.
        return available or models[:1]

    @asynccontextmanager
    async def _slot(self, tier: LlmTier) -> AsyncIterator[None]:
        limit = self.settings.llm_max_concurrency.get(tier.value, 20)
        key = f"llm:inflight:{tier.value}"
        count = await self.redis.incr(key)
        await self.redis.expire(key, INFLIGHT_TTL_SECONDS)
        try:
            if count > limit:
                raise LlmBusyError(log_detail=f"{tier.value}:{count}>{limit}")
            yield
        finally:
            await self.redis.decr(key)

    async def stream(self, tier: LlmTier, call: LlmCall) -> AsyncGenerator[StreamEvent]:
        """첫 텍스트를 내보내기 전에 실패하면 같은 티어의 다음 모델로 넘어간다."""
        async with self._slot(tier):
            last_error: Exception | None = None
            for model in self.candidates(tier):
                emitted = False
                try:
                    async for event in self._stream_model(model, call):
                        if isinstance(event, TextDelta):
                            emitted = True
                        yield event
                    self.breaker.record_success(model)
                    return
                except (TransientProviderError, TimeoutError) as exc:
                    self.breaker.record_failure(model)
                    logger.warning(
                        "llm.provider_failure",
                        extra={"model": model, "error": str(exc) or type(exc).__name__},
                    )
                    if emitted:
                        raise LlmUpstreamError(log_detail=f"{model}:mid_stream") from exc
                    last_error = exc
            raise LlmUpstreamError(log_detail="all_models_failed") from last_error

    async def _stream_model(self, model: str, call: LlmCall) -> AsyncGenerator[StreamEvent]:
        s = self.settings
        effort = call.effort or s.llm_model_effort.get(model)
        if model not in s.llm_model_effort:
            effort = None  # effort를 지원하지 않는 모델(Haiku 4.5)에는 보내지 않는다.
        agen = self.provider.stream(
            model, call, effort=effort, server_fallback=model in s.llm_server_fallback_models
        )
        try:
            first = await asyncio.wait_for(anext(agen), s.llm_first_event_timeout_seconds)
            yield first
            async with asyncio.timeout(s.llm_request_timeout_seconds):
                async for event in agen:
                    yield event
        finally:
            await agen.aclose()

    async def complete(self, tier: LlmTier, call: LlmCall) -> CallResult:
        start = time.perf_counter()
        ttft: int | None = None
        parts: list[str] = []
        done: StreamDone | None = None
        async for event in self.stream(tier, call):
            if isinstance(event, TextDelta):
                if ttft is None:
                    ttft = int((time.perf_counter() - start) * 1000)
                parts.append(event.text)
            elif isinstance(event, StreamDone):
                done = event
        if done is None:
            raise LlmUpstreamError(log_detail="no_final_message")
        check_stop_reason(done)
        latency = int((time.perf_counter() - start) * 1000)
        return CallResult("".join(parts), done, ttft, latency)

    async def complete_structured[M: BaseModel](
        self, tier: LlmTier, call: LlmCall, output_model: type[M]
    ) -> tuple[M, CallResult]:
        """구조화 출력을 받아 검증한다. 검증 실패 시 1회만 재시도한다 (ARCHITECTURE §5.4)."""
        return await retry_on_invalid(lambda: self.complete(tier, call), output_model)


def check_stop_reason(done: StreamDone) -> None:
    if done.stop_reason == "refusal":
        raise LlmRefusedError(log_detail=done.model)
    if done.stop_reason == "max_tokens":
        raise LlmOutputInvalidError(log_detail=f"{done.model}:max_tokens")


async def retry_on_invalid[M: BaseModel](
    run: Callable[[], Awaitable[CallResult]], output_model: type[M]
) -> tuple[M, CallResult]:
    for attempt in range(2):
        result = await run()
        try:
            return output_model.model_validate(json.loads(result.text)), result
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "llm.output_invalid",
                extra={"model": result.done.model, "attempt": attempt, "error": type(exc).__name__},
            )
    raise LlmOutputInvalidError(log_detail="schema_validation")
