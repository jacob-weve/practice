import json
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


@lru_cache
def _catalog(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / locale / "errors.json"
    if not path.exists():
        return {}
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def negotiate_locale(accept_language: str | None) -> str:
    settings = get_settings()
    if accept_language:
        for part in accept_language.split(","):
            tag = part.split(";")[0].strip().lower()
            if not tag:
                continue
            if tag in settings.supported_locales:
                return tag
            base = tag.split("-")[0]
            if base in settings.supported_locales:
                return base
    return settings.default_locale


def translate_error(code: str, locale: str) -> str:
    for candidate in (locale, "en", get_settings().default_locale):
        message = _catalog(candidate).get(code)
        if message:
            return message
    return code
