import json
import logging

from app.core.logging import REDACTED, JsonFormatter, scrub, scrub_text


def test_scrub_masks_sensitive_keys_recursively() -> None:
    data = {
        "user_id": "u1",
        "refresh_token": "abc",
        "nested": {"Authorization": "Bearer x", "draft": "그걸 왜 지금 말해요"},
        "items": [{"email": "a@b.co"}],
    }
    assert scrub(data) == {
        "user_id": "u1",
        "refresh_token": REDACTED,
        "nested": {"Authorization": REDACTED, "draft": REDACTED},
        "items": [{"email": REDACTED}],
    }


def test_scrub_text_masks_jwt_bearer_and_email() -> None:
    text = "token eyJhbGciOi.eyJzdWIiOi.sig Bearer abc.def user a.b@example.com"
    out = scrub_text(text)
    assert "eyJ" not in out
    assert "abc.def" not in out
    assert "example.com" not in out


def test_formatter_scrubs_extra_fields() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "login ok", None, None)
    record.access_token = "secret-value"
    record.user_id = "u1"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["access_token"] == REDACTED
    assert payload["user_id"] == "u1"
    assert payload["event"] == "login ok"
