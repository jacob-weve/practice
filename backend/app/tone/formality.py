"""언어별 격식(존댓말) 수준 매핑 (ARCHITECTURE §10).

formality가 auto면 관계로 정한다. 지침은 모델이 정확히 따르도록 영어로 쓰고,
언어별 문체 이름을 함께 준다.
"""

from typing import Literal

Formality = Literal["auto", "high", "medium", "low"]
Level = Literal["high", "medium", "low"]

RELATION_DEFAULT: dict[str, Level] = {
    "work_superior": "high",
    "client": "high",
    "work_peer": "medium",
    "acquaintance": "medium",
    "family": "low",
    "friend": "low",
    "partner": "low",
}

STYLE: dict[str, dict[Level, str]] = {
    "ko": {
        "high": (
            "Korean 하십시오체/격식 있는 해요체 with honorifics (e.g. '-습니다', '-드리겠습니다')"
        ),
        "medium": "Korean 해요체 (polite informal, e.g. '-해요', '-할까요?')",
        "low": "Korean 반말 (casual, e.g. '-해', '-할래?'), still kind",
    },
    "ja": {
        "high": "Japanese 敬語 (尊敬語・謙譲語, e.g. 'いたします', 'でしょうか')",
        "medium": "Japanese 丁寧語 (です・ます調)",
        "low": "Japanese casual speech (タメ口), still kind",
    },
    "en": {
        "high": "formal English (no contractions, courteous phrasing)",
        "medium": "neutral, friendly English",
        "low": "casual English with contractions",
    },
}


def resolve_level(formality: Formality, relation: str | None) -> Level:
    if formality != "auto":
        return formality
    return RELATION_DEFAULT.get(relation or "", "medium")


def style_instruction(target_lang: str, formality: Formality, relation: str | None) -> str:
    level = resolve_level(formality, relation)
    styles = STYLE.get(target_lang, STYLE["en"])
    return f"Speech level: {level} — use {styles[level]}."
