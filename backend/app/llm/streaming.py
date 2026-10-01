"""LLM 토큰 스트림을 점진적으로 파싱해 SSE 이벤트로 바꾼다."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldCompleted:
    """최상위 필드 하나의 값이 완성됐다."""

    key: str
    value: Any


@dataclass(frozen=True)
class ItemCompleted:
    """최상위 배열 필드(예: variants)의 원소 하나가 완성됐다."""

    key: str
    index: int
    value: Any


ParseEvent = FieldCompleted | ItemCompleted

_SCALAR_END = frozenset(",}] \t\r\n")


class IncrementalObjectParser:
    """최상위가 JSON 객체인 스트림에서 필드·배열 원소가 닫히는 순간을 감지한다.

    문자열·이스케이프·중첩 깊이만 추적하고, 완성된 조각은 json.loads로 파싱한다.
    depth 1 = 최상위 객체 안, depth 2 = 최상위 필드 값(배열/객체) 안.
    """

    def __init__(self, item_keys: frozenset[str] = frozenset()) -> None:
        self.item_keys = item_keys
        self._text = ""
        self._pos = 0
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._expect_key = False
        self._key_start: int | None = None
        self._key: str | None = None
        self._value_start: int | None = None
        self._item_start: int | None = None
        self._item_index = 0
        self._scalar = False  # 현재 열린 값/원소가 숫자·true·false·null인지

    @property
    def text(self) -> str:
        return self._text

    def feed(self, chunk: str) -> Iterator[ParseEvent]:
        self._text += chunk
        while self._pos < len(self._text):
            yield from self._step(self._pos)
            self._pos += 1

    def _step(self, i: int) -> Iterator[ParseEvent]:
        ch = self._text[i]

        if self._in_string:
            if self._escape:
                self._escape = False
            elif ch == "\\":
                self._escape = True
            elif ch == '"':
                self._in_string = False
                if self._key_start is not None:
                    self._key = json.loads(self._text[self._key_start : i + 1])
                    self._key_start = None
                else:
                    yield from self._close_if_top(i + 1)
            return

        if self._scalar and ch in _SCALAR_END:
            self._scalar = False
            yield from self._close_if_top(i)

        if ch == '"':
            self._in_string = True
            if self._depth == 1 and self._expect_key:
                self._key_start = i
                self._expect_key = False
            else:
                self._open_value(i)
        elif ch in "{[":
            self._open_value(i)
            self._depth += 1
            if self._depth == 1:
                self._expect_key = True
        elif ch in "}]":
            self._depth -= 1
            yield from self._close_if_top(i + 1)
        elif ch == ",":
            if self._depth == 1:
                self._expect_key = True
        elif ch not in _SCALAR_END and ch != ":":
            if not self._scalar:
                self._open_value(i)
                self._scalar = True

    def _open_value(self, i: int) -> None:
        if self._depth == 1 and self._key is not None and self._value_start is None:
            self._value_start = i
            self._item_index = 0
        elif (
            self._depth == 2
            and self._key in self.item_keys
            and self._value_start is not None
            and self._text[self._value_start] == "["
            and self._item_start is None
        ):
            self._item_start = i

    def _close_if_top(self, end: int) -> Iterator[ParseEvent]:
        """방금 닫힌 값이 최상위 필드 값이거나 그 배열의 원소면 이벤트를 낸다."""
        if self._depth == 2 and self._item_start is not None:
            assert self._key is not None  # noqa: S101
            value = json.loads(self._text[self._item_start : end])
            yield ItemCompleted(self._key, self._item_index, value)
            self._item_index += 1
            self._item_start = None
        elif self._depth == 1 and self._value_start is not None:
            assert self._key is not None  # noqa: S101
            yield FieldCompleted(self._key, json.loads(self._text[self._value_start : end]))
            self._value_start = None
            self._key = None


def sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


SSE_KEEPALIVE = ": keep-alive\n\n"
