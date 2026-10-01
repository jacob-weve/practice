from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.schemas import EmotionLabel, Intent, RedFlagType, Severity

Lang = Literal["ko", "en", "ja"]
Persona = Literal[
    "affectionate", "polite", "polite_decline", "concise_business", "humorous", "apology"
]
Relation = Literal[
    "work_superior", "work_peer", "client", "partner", "family", "friend", "acquaintance"
]
Zone = Literal["cold", "calm", "warning", "danger"]

# 서비스 한도(PRD NFR-SEC-07). 스키마의 max_length는 비정상적으로 큰 바디를 막는 상한이고,
# 서비스 한도 초과는 INPUT_TOO_LONG(413)으로 따로 알린다.
CONTEXT_LIMIT = 2000
DRAFT_LIMIT = 1000
HARD_CAP = 20_000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TransformOptions(StrictModel):
    include_rationale: bool = True
    emoji: Literal["none", "light", "rich"] = "light"


class ToneTransformRequest(StrictModel):
    context: str | None = Field(default=None, max_length=HARD_CAP)
    draft: str = Field(min_length=1, max_length=HARD_CAP)
    persona: Persona
    relation: Relation | None = None
    target_lang: Lang
    formality: Literal["auto", "high", "medium", "low"] = "auto"
    options: TransformOptions = Field(default_factory=TransformOptions)


class ToneAnalyzeRequest(StrictModel):
    text: str = Field(min_length=1, max_length=HARD_CAP)
    context: str | None = Field(default=None, max_length=HARD_CAP)
    relation: Relation | None = None


class EmotionOut(StrictModel):
    temperature: int
    zone: Zone
    labels: list[EmotionLabel]


class RedFlagOut(StrictModel):
    start: int = Field(description="draft 기준 UTF-16 code unit 오프셋")
    end: int
    text: str
    type: RedFlagType
    severity: Severity
    reason: str
    suggestion: str


class VariantOut(StrictModel):
    kind: Literal["primary", "softer", "concise"]
    text: str
    expected_temperature: int
    rationale: str | None


class TransformMeta(StrictModel):
    model_tier: Literal["light", "heavy"]
    source_lang: str
    target_lang: str
    latency_ms: int | None


class ToneTransformResponse(StrictModel):
    request_id: str
    intent: Intent
    emotion: EmotionOut
    red_flags: list[RedFlagOut]
    variants: list[VariantOut]
    meta: TransformMeta


class ToneAnalyzeResponse(StrictModel):
    request_id: str
    emotion: EmotionOut
    red_flags: list[RedFlagOut]


class PersonaOut(StrictModel):
    key: str
    display_name: str
    description: str
    icon: str | None


class ToneOptionsResponse(StrictModel):
    personas: list[PersonaOut]
    relations: list[str]
    languages: list[str]
