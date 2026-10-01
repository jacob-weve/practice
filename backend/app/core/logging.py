import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"

# 키 이름에 이 단어가 포함되면 값을 통째로 가린다 (CLAUDE.md §4.2).
SENSITIVE_KEY_PARTS = (
    "token",
    "authorization",
    "cookie",
    "secret",
    "password",
    "code_verifier",
    "email",
    "draft",
    "context",
    "message",
    "conversation",
)
# 키 이름과 무관하게 값 자체가 비밀처럼 보이는 패턴.
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_STD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def scrub_text(text: str) -> str:
    text = _JWT_RE.sub(REDACTED, text)
    text = _BEARER_RE.sub(f"Bearer {REDACTED}", text)
    return _EMAIL_RE.sub(REDACTED, text)


def scrub(value: Any, key: str | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {k: scrub(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": scrub_text(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                payload[key] = scrub(value, key)
        if record.exc_info:
            payload["exc"] = scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # httpx는 요청 URL(쿼리에 code/token 포함 가능)을 INFO로 남기므로 WARNING 이상만 허용한다.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
