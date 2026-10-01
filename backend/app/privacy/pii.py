"""PII 탐지·마스킹 (ARCHITECTURE §8).

정규식으로 잡을 수 있는 식별자는 정확도가 높은 순서로 치환한다. 인명은 NER 없이
호칭 패턴(민수씨, 김대리님)만 잡는다 — 품질 로그용 기본 방어선이며 완전하지 않다.
"""

import re
from dataclasses import dataclass, field

# 순서가 중요하다: 더 구체적인 패턴(주민번호, 카드)을 일반 패턴(계좌, 전화)보다 먼저 치환한다.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("RRN", re.compile(r"(?<!\d)\d{6}\s?-\s?[1-8]\d{6}(?!\d)")),
    ("CARD", re.compile(r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)")),
    (
        "PHONE",
        re.compile(
            r"(?<!\d)(?:\+82[- ]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)"
            r"|(?<!\d)0(?:2|[3-6][1-5])[- .]\d{3,4}[- .]\d{4}(?!\d)"
        ),
    ),
    ("ACCOUNT", re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?:-\d{1,3})?(?!\d)")),
    (
        "ADDRESS",
        re.compile(
            r"[가-힣]{1,10}(?:시|도)\s[가-힣]{1,10}(?:구|군|시)\s[가-힣0-9]{1,15}(?:로|길|동)"
            r"(?:\s?\d{1,5}(?:-\d{1,5})?)?"
        ),
    ),
    (
        "NAME",
        re.compile(
            r"(?<![가-힣])[가-힣]{2,4}(?=\s?(?:씨|님|선배|후배|대리|과장|차장|부장|팀장|교수|선생))"
        ),
    ),
]

# 호칭 앞의 일반 명사가 이름으로 잡히지 않게 제외한다.
_NAME_STOPWORDS = frozenset(
    {
        "고객",
        "회원",
        "사용자",
        "여러분",
        "어머",
        "아버",
        "학부모",
        "담당자",
        "기사",
        "사장",
        "팀장",
        "과장",
        "부장",
        "차장",
        "대리",
        "선배",
        "후배",
        "교수",
        "선생",
        "선생님",
        "원장",
        "실장",
        "대표",
        "이사",
        "본부장",
        "주임",
        "사원",
        "형님",
        "언니",
        "누나",
        "오빠",
    }
)


@dataclass
class MaskResult:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # 토큰 → 원문 (메모리에서만 사용)
    types: set[str] = field(default_factory=set)


def mask(text: str, result: MaskResult | None = None) -> MaskResult:
    """같은 MaskResult를 넘기면 여러 텍스트에서 같은 값은 같은 토큰으로 치환된다."""
    result = result or MaskResult(text="")
    reverse = {v: k for k, v in result.mapping.items()}
    counters: dict[str, int] = {}
    for token in result.mapping:
        kind = token[1:].split("_")[0]
        counters[kind] = max(counters.get(kind, 0), int(token[:-1].rsplit("_", 1)[1]))

    masked = text
    for kind, pattern in _PATTERNS:

        def replace(match: re.Match[str], kind: str = kind) -> str:
            value = match.group(0)
            if kind == "NAME" and value in _NAME_STOPWORDS:
                return value
            # 날짜(2026-10-01)나 짧은 번호가 계좌로 잡히지 않게 자릿수로 거른다.
            if kind == "ACCOUNT" and sum(c.isdigit() for c in value) < 10:
                return value
            if value in reverse:
                return reverse[value]
            counters[kind] = counters.get(kind, 0) + 1
            token = f"[{kind}_{counters[kind]}]"
            reverse[value] = token
            result.mapping[token] = value
            result.types.add(kind)
            return token

        masked = pattern.sub(replace, masked)
    result.text = masked
    return result


def unmask(text: str, mapping: dict[str, str]) -> str:
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text
