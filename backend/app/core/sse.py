"""SSE 응답 공통 처리 (ARCHITECTURE §5.3)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.core.errors import AppError
from app.core.i18n import negotiate_locale, translate_error
from app.llm.streaming import SSE_KEEPALIVE, sse_event

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 15.0
_END = object()

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # Nginx가 스트림을 버퍼링하지 않게 한다.
}


def wants_sse(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "")


async def _with_keepalive(
    events: AsyncIterator[tuple[str, dict[str, Any]]], interval: float
) -> AsyncIterator[tuple[str, dict[str, Any]] | None]:
    """이벤트 사이가 interval보다 길면 None(keep-alive)을 끼워 넣는다."""
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in events:
                await queue.put(item)
            await queue.put(_END)
        except BaseException as exc:  # noqa: BLE001  소비자 쪽에서 다시 올린다
            await queue.put(exc)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                yield None
                continue
            if item is _END:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        aclose = getattr(events, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()


async def _encode(
    request: Request,
    events: AsyncIterator[tuple[str, dict[str, Any]]],
    keepalive: float,
) -> AsyncIterator[str]:
    locale = negotiate_locale(request.headers.get("accept-language"))
    request_id = str(getattr(request.state, "request_id", "-"))
    try:
        async for item in _with_keepalive(events, keepalive):
            if await request.is_disconnected():
                # 클라이언트가 떠나면 LLM 스트림을 끊어 비용이 새지 않게 한다(finally에서 정리).
                logger.info("sse.client_disconnected")
                return
            yield SSE_KEEPALIVE if item is None else sse_event(*item)
    except AppError as exc:
        logger.warning("sse.error", extra={"code": exc.code, "detail": exc.log_detail})
        yield sse_event(
            "error",
            {
                "code": exc.code,
                "message": translate_error(exc.code, locale),
                "request_id": request_id,
                "details": exc.details,
            },
        )
    except Exception:
        logger.exception("sse.unhandled_error")
        yield sse_event(
            "error",
            {
                "code": "INTERNAL_ERROR",
                "message": translate_error("INTERNAL_ERROR", locale),
                "request_id": request_id,
                "details": {},
            },
        )


def sse_response(
    request: Request,
    events: AsyncIterator[tuple[str, dict[str, Any]]],
    headers: dict[str, str] | None = None,
    keepalive: float = KEEPALIVE_SECONDS,
) -> StreamingResponse:
    return StreamingResponse(
        _encode(request, events, keepalive),
        media_type="text/event-stream",
        headers={**SSE_HEADERS, **(headers or {})},
    )
