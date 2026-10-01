import pytest

from app.llm.schemas import RedFlag
from app.tone.text import detect_lang, locate_red_flags, zone_for


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("내일은 어려워요", "ko"),
        ("ㅇㅇ", "ko"),
        ("今日はちょっと無理です", "ja"),
        ("I can't make it tomorrow", "en"),
        ("OK 알겠어", "ko"),
        ("123!!", "en"),
    ],
)
def test_detect_lang(text: str, lang: str) -> None:
    assert detect_lang(text) == lang


@pytest.mark.parametrize(
    ("temp", "zone"),
    [
        (0, "cold"),
        (30, "cold"),
        (31, "calm"),
        (60, "calm"),
        (61, "warning"),
        (80, "warning"),
        (81, "danger"),
        (100, "danger"),
    ],
)
def test_zone_boundaries(temp: int, zone: str) -> None:
    assert zone_for(temp) == zone


def flag(text: str) -> RedFlag:
    return RedFlag(text=text, type="cold", severity="low", reason="r", suggestion="s")


def test_offsets_are_utf16_code_units() -> None:
    draft = "😡 진짜 왜 그래"  # 😡는 UTF-16에서 2 code unit
    [located] = locate_red_flags(draft, [flag("왜 그래")])
    assert (located.start, located.end) == (6, 10)
    # JavaScript의 draft.slice(6, 10)과 같은 범위인지 UTF-16으로 확인
    units = draft.encode("utf-16-le")
    assert units[located.start * 2 : located.end * 2].decode("utf-16-le") == "왜 그래"


def test_repeated_phrases_use_successive_occurrences() -> None:
    draft = "몰라. 진짜 몰라."
    located = locate_red_flags(draft, [flag("몰라"), flag("몰라"), flag("몰라")])
    assert [(f.start, f.end) for f in located] == [(0, 2), (7, 9)]


def test_blank_and_missing_flags_are_dropped_and_result_sorted() -> None:
    draft = "A then B"
    located = locate_red_flags(draft, [flag("B"), flag("  "), flag("Z"), flag(" A ")])
    assert [f.text for f in located] == ["A", "B"]
