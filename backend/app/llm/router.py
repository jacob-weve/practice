"""요청 특성에 따라 경량(light)·고성능(heavy) 티어를 고른다 (ARCHITECTURE §6)."""

from dataclasses import dataclass

from app.db.models import LlmTier

HEAVY_PERSONAS = frozenset({"polite_decline", "apology"})
LONG_INPUT_CHARS = 600


@dataclass(frozen=True)
class RouteInput:
    kind: str
    context_chars: int = 0
    draft_chars: int = 0
    persona: str | None = None
    source_lang: str | None = None
    target_lang: str | None = None
    plan: str = "free"
    template_tier: LlmTier = LlmTier.LIGHT


def choose_tier(r: RouteInput) -> LlmTier:
    if r.template_tier is LlmTier.HEAVY or r.kind == "reply_interpret":
        return LlmTier.HEAVY
    if r.plan == "premium":
        return LlmTier.HEAVY
    if r.context_chars + r.draft_chars > LONG_INPUT_CHARS:
        return LlmTier.HEAVY
    if r.source_lang and r.target_lang and r.source_lang != r.target_lang:
        return LlmTier.HEAVY
    if r.persona in HEAVY_PERSONAS:
        return LlmTier.HEAVY
    return LlmTier.LIGHT
