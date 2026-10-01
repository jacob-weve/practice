import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AppError,
    InputRejectedError,
    InputTooLongError,
    LlmOutputInvalidError,
    LlmRefusedError,
    ValidationAppError,
)
from app.db.models import LlmTier, LogStatus, ToneOption, TransformKind, User
from app.llm import guardrails
from app.llm.client import LlmCall, LlmClient
from app.llm.pipeline import StreamStats, guarded_stream
from app.llm.prompts import (
    LoadedTemplate,
    build_messages,
    data_block,
    load_template,
    normalize_input,
)
from app.llm.router import RouteInput, choose_tier
from app.llm.schemas import (
    Emotion,
    Intent,
    RedFlag,
    ToneAnalyzeOutput,
    ToneTransformOutput,
    Variant,
)
from app.llm.streaming import FieldCompleted, IncrementalObjectParser, ItemCompleted
from app.privacy.log_writer import LogEntry, TransformationLogWriter
from app.tone.schemas import (
    CONTEXT_LIMIT,
    DRAFT_LIMIT,
    PersonaOut,
    ToneAnalyzeRequest,
    ToneAnalyzeResponse,
    ToneOptionsResponse,
    ToneTransformRequest,
    ToneTransformResponse,
    TransformMeta,
    VariantOut,
)
from app.tone.text import detect_lang, emotion_out, locate_red_flags

logger = logging.getLogger(__name__)

RELATIONS = ["work_superior", "work_peer", "client", "partner", "family", "friend", "acquaintance"]
LANGUAGES = ["ko", "en", "ja"]
RED_FLAGS = TypeAdapter(list[RedFlag])

SseEvent = tuple[str, dict[str, Any]]


def status_for(exc: Exception) -> LogStatus:
    if isinstance(exc, InputRejectedError):
        return LogStatus.GUARDRAIL_BLOCKED
    if isinstance(exc, LlmRefusedError):
        return LogStatus.REFUSED
    if isinstance(exc, LlmOutputInvalidError | ValidationError):
        return LogStatus.SCHEMA_INVALID
    return LogStatus.LLM_ERROR


@dataclass
class PreparedCall:
    """스트리밍 전에 DB에서 읽어 둔 모든 것. 스트림 안에서는 요청 DB 세션을 쓰지 않는다."""

    user_id: Any
    kind: TransformKind
    tier: LlmTier
    call: LlmCall
    template: LoadedTemplate
    guard_template: LoadedTemplate
    guard_texts: list[str]
    context: str | None
    draft: str
    source_lang: str
    target_lang: str
    persona: str | None = None
    include_rationale: bool = True
    request_id: str = "-"
    output: dict[str, Any] = field(default_factory=dict)


class ToneService:
    def __init__(
        self,
        db: AsyncSession,
        llm: LlmClient,
        settings: Settings,
        log_writer: TransformationLogWriter,
    ) -> None:
        self.db = db
        self.llm = llm
        self.settings = settings
        self.log_writer = log_writer

    @property
    def canary(self) -> str:
        return self.settings.llm_canary_token.get_secret_value()

    # ------------------------------------------------------------------ options
    async def options(self, locale: str) -> ToneOptionsResponse:
        rows = (
            await self.db.execute(
                select(ToneOption)
                .where(ToneOption.is_active.is_(True), ToneOption.locale.in_([locale, "ko"]))
                .order_by(ToneOption.sort_order)
            )
        ).scalars()
        by_key: dict[str, ToneOption] = {}
        for row in rows:
            if row.key not in by_key or row.locale == locale:
                by_key[row.key] = row
        personas = [
            PersonaOut(
                key=r.key, display_name=r.display_name, description=r.description, icon=r.icon
            )
            for r in sorted(by_key.values(), key=lambda r: r.sort_order)
        ]
        return ToneOptionsResponse(personas=personas, relations=RELATIONS, languages=LANGUAGES)

    # ------------------------------------------------------------------ prepare
    async def _persona_directive(self, key: str) -> str:
        directive = await self.db.scalar(
            select(ToneOption.prompt_directive)
            .where(ToneOption.key == key, ToneOption.is_active.is_(True))
            .limit(1)
        )
        if directive is None:
            raise ValidationAppError(log_detail=f"unknown_persona:{key}")
        return directive

    async def prepare_transform(self, user: User, req: ToneTransformRequest) -> PreparedCall:
        context = _normalize(req.context)
        draft = _normalize(req.draft) or ""
        if len(draft) > DRAFT_LIMIT or len(context or "") > CONTEXT_LIMIT:
            raise InputTooLongError()
        if not draft.strip():
            raise ValidationAppError(log_detail="empty_draft")

        directive = await self._persona_directive(req.persona)
        template = await load_template(self.db, "tone_transform")
        source_lang = detect_lang(draft)
        tier = choose_tier(
            RouteInput(
                kind="tone_transform",
                context_chars=len(context or ""),
                draft_chars=len(draft),
                persona=req.persona,
                source_lang=source_lang,
                target_lang=req.target_lang,
                plan=user.plan,
                template_tier=template.model_tier,
            )
        )
        options = data_block(
            "options",
            f"Persona instructions: {directive}\nEmoji usage: {req.options.emoji}.",
            persona=req.persona,
            relation=req.relation or "unspecified",
            target_lang=req.target_lang,
            ui_lang=user.ui_locale,
            formality=req.formality,
        )
        built = build_messages(
            template,
            {
                "options": options,
                "context": data_block("context", context or "(none)"),
                "draft": data_block("draft", draft),
            },
        )
        return PreparedCall(
            user_id=user.id,
            kind=TransformKind.TONE_TRANSFORM,
            tier=tier,
            call=self._call(template, built.system, built.user),
            template=template,
            guard_template=await guardrails.load_guard_template(self.db),
            guard_texts=[t for t in (context, draft) if t],
            context=context,
            draft=draft,
            source_lang=source_lang,
            target_lang=req.target_lang,
            persona=req.persona,
            include_rationale=req.options.include_rationale,
        )

    def _call(self, template: LoadedTemplate, system: str, user: str) -> LlmCall:
        return LlmCall(
            system=guardrails.with_canary(system, self.canary),
            user=user,
            output_schema=template.output_schema,
            max_tokens=template.max_tokens,
            effort=template.effort,
        )

    # -------------------------------------------------------------- transform
    async def stream_transform(self, p: PreparedCall, request_id: str) -> AsyncIterator[SseEvent]:
        """SSE 이벤트를 만든다: meta → analysis → red_flags → variant×N → done."""
        p.request_id = request_id
        yield "meta", {"request_id": request_id, "model_tier": p.tier.value}
        stats = StreamStats()
        parser = IncrementalObjectParser(item_keys=frozenset({"variants"}))
        intent: Intent | None = None
        status = LogStatus.SUCCESS
        try:
            guard = guardrails.check(p.guard_texts, template=p.guard_template, llm=self.llm)
            async for chunk in guarded_stream(self.llm, p.tier, p.call, guard, stats):
                for ev in parser.feed(chunk):
                    for out in self._transform_piece(p, ev, intent):
                        if out[0] == "_intent":
                            intent = Intent.model_validate(out[1])
                        else:
                            yield out
            guardrails.assert_no_canary(parser.text, self.canary)
            try:
                ToneTransformOutput.model_validate(json.loads(parser.text))
            except (ValueError, ValidationError) as exc:
                raise LlmOutputInvalidError(log_detail="final_validation") from exc
            if not p.output.get("variants"):
                raise LlmOutputInvalidError(log_detail="no_safe_variants")
            assert stats.done is not None  # noqa: S101
            yield (
                "done",
                {
                    "usage": {
                        "input_tokens": stats.done.input_tokens,
                        "output_tokens": stats.done.output_tokens,
                        "cached_tokens": stats.done.cached_tokens,
                    },
                    "latency_ms": stats.latency_ms,
                },
            )
        except (AppError, ValidationError) as exc:
            status = status_for(exc)
            if isinstance(exc, ValidationError):
                raise LlmOutputInvalidError(log_detail="piece_validation") from exc
            raise
        finally:
            await self._log(p, stats, status)

    def _transform_piece(
        self, p: PreparedCall, ev: FieldCompleted | ItemCompleted, intent: Intent | None
    ) -> list[SseEvent]:
        guardrails.assert_no_canary(json.dumps(ev.value, ensure_ascii=False), self.canary)
        if isinstance(ev, FieldCompleted):
            if ev.key == "intent":
                p.output["intent"] = Intent.model_validate(ev.value).model_dump()
                return [("_intent", p.output["intent"])]
            if ev.key == "emotion":
                emotion = emotion_out(Emotion.model_validate(ev.value))
                p.output["emotion"] = emotion.model_dump()
                return [
                    ("analysis", {"intent": p.output.get("intent"), "emotion": p.output["emotion"]})
                ]
            if ev.key == "red_flags":
                located = locate_red_flags(p.draft, RED_FLAGS.validate_python(ev.value))
                p.output["red_flags"] = [f.model_dump() for f in located]
                return [("red_flags", {"red_flags": p.output["red_flags"]})]
            return []
        if ev.key != "variants":
            return []
        variant = Variant.model_validate(ev.value)
        if guardrails.is_unsafe_output(variant.text):
            logger.warning("guardrail.unsafe_variant_dropped", extra={"kind": variant.kind})
            return []
        out = VariantOut(
            kind=variant.kind,
            text=variant.text,
            expected_temperature=variant.expected_temperature,
            rationale=variant.rationale if p.include_rationale else None,
        ).model_dump()
        p.output.setdefault("variants", []).append(out)
        return [("variant", {"index": ev.index, **out})]

    async def transform(
        self, user: User, req: ToneTransformRequest, request_id: str
    ) -> ToneTransformResponse:
        """JSON 응답. 스트림을 모아 조립하고, 출력 검증 실패는 1회 재시도한다."""
        for attempt in range(2):
            p = await self.prepare_transform(user, req)
            latency: int | None = None
            try:
                async for name, data in self.stream_transform(p, request_id):
                    if name == "done":
                        latency = data["latency_ms"]
            except LlmOutputInvalidError:
                if attempt == 0:
                    continue
                raise
            return ToneTransformResponse(
                request_id=request_id,
                intent=Intent.model_validate(p.output["intent"]),
                emotion=p.output["emotion"],
                red_flags=p.output.get("red_flags", []),
                variants=p.output["variants"],
                meta=TransformMeta(
                    model_tier=p.tier.value,
                    source_lang=p.source_lang,
                    target_lang=p.target_lang,
                    latency_ms=latency,
                ),
            )
        raise LlmOutputInvalidError(log_detail="unreachable")  # pragma: no cover

    # ---------------------------------------------------------------- analyze
    async def analyze(
        self, user: User, req: ToneAnalyzeRequest, request_id: str
    ) -> ToneAnalyzeResponse:
        context = _normalize(req.context)
        text = _normalize(req.text) or ""
        if len(text) > DRAFT_LIMIT or len(context or "") > CONTEXT_LIMIT:
            raise InputTooLongError()
        template = await load_template(self.db, "tone_analyze")
        guard_template = await guardrails.load_guard_template(self.db)
        options = data_block(
            "options",
            "Analyze only.",
            relation=req.relation or "unspecified",
            ui_lang=user.ui_locale,
        )
        built = build_messages(
            template,
            {
                "options": options,
                "context": data_block("context", context or "(none)"),
                "draft": data_block("draft", text),
            },
        )
        p = PreparedCall(
            user_id=user.id,
            kind=TransformKind.TONE_ANALYZE,
            tier=LlmTier.LIGHT,
            call=self._call(template, built.system, built.user),
            template=template,
            guard_template=guard_template,
            guard_texts=[t for t in (context, text) if t],
            context=context,
            draft=text,
            source_lang=detect_lang(text),
            target_lang=detect_lang(text),
            request_id=request_id,
        )
        for attempt in range(2):
            stats = StreamStats()
            status = LogStatus.SUCCESS
            try:
                guard = guardrails.check(p.guard_texts, template=guard_template, llm=self.llm)
                parts = [c async for c in guarded_stream(self.llm, p.tier, p.call, guard, stats)]
                raw = "".join(parts)
                guardrails.assert_no_canary(raw, self.canary)
                try:
                    parsed = ToneAnalyzeOutput.model_validate(json.loads(raw))
                except (ValueError, ValidationError) as exc:
                    raise LlmOutputInvalidError(log_detail="analyze_validation") from exc
                emotion = emotion_out(parsed.emotion)
                flags = locate_red_flags(text, parsed.red_flags)
                p.output = {
                    "emotion": emotion.model_dump(),
                    "red_flags": [f.model_dump() for f in flags],
                }
                return ToneAnalyzeResponse(request_id=request_id, emotion=emotion, red_flags=flags)
            except AppError as exc:
                status = status_for(exc)
                if isinstance(exc, LlmOutputInvalidError) and attempt == 0:
                    continue
                raise
            finally:
                await self._log(p, stats, status)
        raise LlmOutputInvalidError(log_detail="unreachable")  # pragma: no cover

    # -------------------------------------------------------------------- log
    async def _log(self, p: PreparedCall, stats: StreamStats, status: LogStatus) -> None:
        done = stats.done
        emotion = p.output.get("emotion") or {}
        await self.log_writer.write(
            LogEntry(
                user_id=p.user_id,
                request_id=p.request_id,
                kind=p.kind,
                status=status,
                model_tier=p.tier,
                model_id=done.model if done else "-",
                prompt_template_id=p.template.id,
                tone_option_key=p.persona,
                source_lang=p.source_lang,
                target_lang=p.target_lang,
                context=p.context,
                draft=p.draft,
                output=p.output or None,
                emotion_temperature=emotion.get("temperature"),
                red_flag_count=len(p.output["red_flags"]) if "red_flags" in p.output else None,
                guardrail_score=stats.guard.score if stats.guard else None,
                input_tokens=done.input_tokens if done else None,
                output_tokens=done.output_tokens if done else None,
                cached_tokens=done.cached_tokens if done else None,
                ttft_ms=stats.ttft_ms,
                latency_ms=stats.latency_ms,
            )
        )


def _normalize(text: str | None) -> str | None:
    return normalize_input(text) if text is not None else None
