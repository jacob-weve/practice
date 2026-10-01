import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("locale", ["ko", "en", "ja"])
def test_backend_and_web_error_catalogs_match(locale: str) -> None:
    backend = json.loads((ROOT / "backend/app/locales" / locale / "errors.json").read_text())
    web = json.loads((ROOT / "web/locales" / locale / "errors.json").read_text())
    assert backend == web


def test_every_locale_has_the_same_error_codes() -> None:
    codes = {
        loc: set(json.loads((ROOT / "backend/app/locales" / loc / "errors.json").read_text()))
        for loc in ("ko", "en", "ja")
    }
    assert codes["ko"] == codes["en"] == codes["ja"]
