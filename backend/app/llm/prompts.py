"""프롬프트 조립. 시스템 지침과 사용자 입력을 구조적으로 분리한다 (CLAUDE.md §4.3)."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LlmTier, PromptTemplate

# 사용자 입력을 감싸는 데이터 블록 태그. 입력 안의 같은 태그는 무력화한다.
DATA_TAGS = ("context", "draft", "message", "conversation", "turn", "options", "input")
_TAG_RE = re.compile(r"<\s*(/?)\s*(" + "|".join(DATA_TAGS) + r")\b", re.IGNORECASE)
_ZERO_WIDTH_RE = re.compile("[​-‏‪-‮⁠-⁤﻿]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_input(text: str) -> str:
    """NFC 정규화, 제로폭·방향 제어·제어 문자 제거. 줄바꿈과 탭은 남긴다."""
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    return _CONTROL_RE.sub("", text)


def escape_user_block(text: str) -> str:
    """데이터 블록 구분 태그를 위조하지 못하게 '<'를 전각 '＜'로 바꾼다."""
    return _TAG_RE.sub(lambda m: f"＜{m.group(1)}{m.group(2)}", text)


def data_block(tag: str, text: str, **attrs: str) -> str:
    if tag not in DATA_TAGS:
        raise ValueError(f"unknown data tag: {tag}")
    rendered_attrs = "".join(f' {k}="{_attr(v)}"' for k, v in attrs.items())
    return f"<{tag}{rendered_attrs}>\n{escape_user_block(text)}\n</{tag}>"


def _attr(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-. ]", "", value)[:60]


@dataclass(frozen=True)
class LoadedTemplate:
    id: Any
    name: str
    version: int
    system_prompt: str
    user_template: str
    output_schema: dict[str, Any]
    model_tier: LlmTier
    effort: str | None
    max_tokens: int


async def load_template(db: AsyncSession, name: str, locale: str = "any") -> LoadedTemplate:
    """활성 템플릿을 고른다. 로케일 전용 템플릿이 없으면 'any'를 쓴다."""
    rows = (
        await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.name == name,
                PromptTemplate.is_active.is_(True),
                PromptTemplate.locale.in_([locale, "any"]),
            )
        )
    ).scalars()
    by_locale = {row.locale: row for row in rows}
    row = by_locale.get(locale) or by_locale.get("any")
    if row is None:
        raise LookupError(f"no active prompt template: {name}")
    return LoadedTemplate(
        id=row.id,
        name=row.name,
        version=row.version,
        system_prompt=row.system_prompt,
        user_template=row.user_template,
        output_schema=row.output_schema,
        model_tier=row.model_tier,
        effort=row.effort,
        max_tokens=row.max_tokens,
    )


@dataclass(frozen=True)
class BuiltPrompt:
    system: str
    user: str


def build_messages(template: LoadedTemplate, blocks: dict[str, str]) -> BuiltPrompt:
    """user_template의 {이름} 자리에 미리 렌더링한 data_block을 넣는다.

    str.format을 쓰지 않는다: 사용자 입력 안의 중괄호가 서식 지정자로 해석되지 않게 하기 위해서다.
    """
    user = template.user_template
    for name, rendered in blocks.items():
        user = user.replace("{" + name + "}", rendered)
    leftover = re.findall(r"\{[a-z_]+\}", template.user_template)
    missing = [p for p in leftover if p[1:-1] not in blocks]
    if missing:
        raise ValueError(f"unfilled placeholders: {missing}")
    return BuiltPrompt(system=template.system_prompt, user=user)
