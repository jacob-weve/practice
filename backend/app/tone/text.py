"""초안 텍스트에 대한 결정적(LLM 없는) 계산."""

from app.llm.schemas import Emotion, RedFlag
from app.tone.schemas import EmotionOut, RedFlagOut, Zone


def detect_lang(text: str) -> str:
    """문자 체계로 언어를 추정한다. 라우팅(교차 언어 여부) 용도라 대략이면 충분하다."""
    hangul = kana = latin = 0
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3 or 0x3131 <= code <= 0x318E:
            hangul += 1
        elif 0x3040 <= code <= 0x30FF:
            kana += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    if hangul >= max(kana, latin) and hangul > 0:
        return "ko"
    if kana > 0 and kana >= latin / 4:
        return "ja"
    return "en"


def zone_for(temperature: int) -> Zone:
    if temperature <= 30:
        return "cold"
    if temperature <= 60:
        return "calm"
    if temperature <= 80:
        return "warning"
    return "danger"


def emotion_out(emotion: Emotion) -> EmotionOut:
    return EmotionOut(
        temperature=emotion.temperature,
        zone=zone_for(emotion.temperature),
        labels=emotion.labels,
    )


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def locate_red_flags(draft: str, flags: list[RedFlag]) -> list[RedFlagOut]:
    """LLM이 복사한 문자열을 초안에서 찾아 오프셋을 붙인다. 못 찾은 항목은 버린다.

    같은 문자열이 여러 번 나오면 앞에서부터 아직 쓰지 않은 위치를 쓴다.
    오프셋은 웹 클라이언트(JavaScript 문자열)와 맞추기 위해 UTF-16 code unit 기준이다.
    """
    used_from: dict[str, int] = {}
    located: list[RedFlagOut] = []
    for flag in flags:
        needle = flag.text.strip()
        if not needle:
            continue
        start = draft.find(needle, used_from.get(needle, 0))
        if start < 0:
            continue
        end = start + len(needle)
        used_from[needle] = end
        located.append(
            RedFlagOut(
                start=_utf16_len(draft[:start]),
                end=_utf16_len(draft[:end]),
                text=needle,
                type=flag.type,
                severity=flag.severity,
                reason=flag.reason,
                suggestion=flag.suggestion,
            )
        )
    return sorted(located, key=lambda f: f.start)
