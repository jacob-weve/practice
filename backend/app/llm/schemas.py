"""LLM 구조화 출력 스키마.

필드 순서가 곧 생성 순서다. 스트리밍에서 빨리 보여줄 수 있는 필드(의도·감정)를 앞에,
오래 걸리는 필드(변환 문장)를 뒤에 둔다 (ARCHITECTURE §5.2).
"""

from typing import Any, Literal

from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, Field


class LlmModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


IntentLabel = Literal[
    "accept", "decline", "request", "apology", "inform", "complain", "gratitude", "other"
]
EmotionName = Literal[
    "anger", "frustration", "sadness", "anxiety", "joy", "affection", "neutral", "indifference"
]
RedFlagType = Literal[
    "sarcasm",
    "blame",
    "command",
    "passive_aggressive",
    "belittling",
    "absolute",
    "ambiguous",
    "cold",
]
Severity = Literal["low", "medium", "high"]


class Intent(LlmModel):
    label: IntentLabel
    confidence: float = Field(ge=0, le=1)


class EmotionLabel(LlmModel):
    name: EmotionName
    score: float = Field(ge=0, le=1)


class Emotion(LlmModel):
    temperature: int = Field(ge=0, le=100, description="0=icy, 50=neutral, 100=furious")
    labels: list[EmotionLabel]


class RedFlag(LlmModel):
    text: str = Field(description="Exact substring copied from the draft")
    type: RedFlagType
    severity: Severity
    reason: str = Field(description="Why it may be misread, written in the UI language")
    suggestion: str = Field(description="Softer replacement, written in the target language")


class Variant(LlmModel):
    kind: Literal["primary", "softer", "concise"]
    text: str
    expected_temperature: int = Field(ge=0, le=100)
    rationale: str = Field(description="One sentence in the UI language")


class ToneTransformOutput(LlmModel):
    intent: Intent
    emotion: Emotion
    red_flags: list[RedFlag]
    variants: list[Variant] = Field(min_length=1, max_length=3)


class ToneAnalyzeOutput(LlmModel):
    emotion: Emotion
    red_flags: list[RedFlag]


class Interpretation(LlmModel):
    summary: str
    likelihood: float = Field(ge=0, le=1)
    signals: list[str]


class Guide(LlmModel):
    summary: str
    avoid: list[str]
    check_points: list[str]
    overthinking_warning: bool


class SuggestedReply(LlmModel):
    style: Literal["confirm", "empathize", "light_shift"]
    text: str
    rationale: str


class ReplyInterpretOutput(LlmModel):
    message_emotion: Emotion
    interpretations: list[Interpretation] = Field(min_length=1, max_length=3)
    guide: Guide
    suggested_replies: list[SuggestedReply] = Field(min_length=3, max_length=3)


class GuardrailVerdict(LlmModel):
    category: Literal["safe", "injection", "jailbreak", "harmful"]
    score: float = Field(ge=0, le=1, description="Confidence that the input is NOT safe")


OUTPUT_MODELS: dict[str, type[LlmModel]] = {
    "tone_transform": ToneTransformOutput,
    "tone_analyze": ToneAnalyzeOutput,
    "reply_interpret": ReplyInterpretOutput,
    "guardrail_classify": GuardrailVerdict,
}


def api_schema(model: type[BaseModel]) -> dict[str, Any]:
    """구조화 출력 API가 받는 형태로 변환한다(min/max 등은 설명으로 옮기고 클라이언트에서 검증)."""
    return transform_schema(model)
