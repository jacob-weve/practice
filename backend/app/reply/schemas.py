from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.schemas import Guide, Interpretation
from app.tone.schemas import HARD_CAP, EmotionOut, Lang, Relation

MESSAGE_LIMIT = 1000
TURN_LIMIT = 500
CONVERSATION_TURNS = 20
CONVERSATION_LIMIT = 3000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Turn(StrictModel):
    speaker: Literal["me", "them"]
    text: str = Field(min_length=1, max_length=HARD_CAP)
    sent_at: datetime | None = None


class ReplyInterpretRequest(StrictModel):
    message: str = Field(min_length=1, max_length=HARD_CAP)
    conversation: list[Turn] = Field(default_factory=list, max_length=100)
    relation: Relation
    my_concern: str | None = Field(default=None, max_length=300)
    target_lang: Lang = "ko"


class SuggestedReplyOut(StrictModel):
    style: Literal["confirm", "empathize", "light_shift"]
    text: str
    rationale: str


class ReplyInterpretResponse(StrictModel):
    request_id: str
    message_emotion: EmotionOut
    interpretations: list[Interpretation]
    guide: Guide
    suggested_replies: list[SuggestedReplyOut]
    disclaimer: str
