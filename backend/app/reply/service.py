import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, InputTooLongError, LlmOutputInvalidError
from app.db.models import LogStatus, TransformKind, User
from app.llm import guardrails
from app.llm.client import LlmCall, LlmClient
from app.llm.pipeline import StreamStats, guarded_stream, status_for
from app.llm.prompts import build_messages, data_block, load_template, normalize_input
from app.llm.router import RouteInput, choose_tier
from app.llm.schemas import Emotion, Guide, Interpretation, ReplyInterpretOutput, SuggestedReply
from app.llm.streaming import FieldCompleted, IncrementalObjectParser, ItemCompleted
from app.privacy.log_writer import LogEntry, TransformationLogWriter
from app.reply.schemas import (
    CONVERSATION_LIMIT,
    CONVERSATION_TURNS,
    MESSAGE_LIMIT,
    TURN_LIMIT,
    ReplyInterpretRequest,
    ReplyInterpretResponse,
    SuggestedReplyOut,
)
from app.tone.service import PreparedCall
from app.tone.text import detect_lang, emotion_out

logger = logging.getLogger(__name__)

SseEvent = tuple[str, dict[str, Any]]

DISCLAIMERS = {
    "ko": "AI 해석은 참고용이에요. 정확한 마음은 상대방과 직접 대화해서 확인해 주세요.",
    "en": "This is an AI reading for reference only. Talk with them to know how they really feel.",
    "ja": "AIの解釈は参考用です。本当の気持ちは相手と直接話して確かめてください。",
}


class ReplyService:
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

    async def prepare(self, user: User, req: ReplyInterpretRequest) -> PreparedCall:
        message = normalize_input(req.message)
        turns = [(t.speaker, normalize_input(t.text)) for t in req.conversation]
        concern = normalize_input(req.my_concern) if req.my_concern else None
        if (
            len(message) > MESSAGE_LIMIT
            or len(turns) > CONVERSATION_TURNS
            or any(len(text) > TURN_LIMIT for _, text in turns)
            or sum(len(text) for _, text in turns) > CONVERSATION_LIMIT
        ):
            raise InputTooLongError()

        template = await load_template(self.db, "reply_interpret")
        tier = choose_tier(
            RouteInput(kind="reply_interpret", plan=user.plan, template_tier=template.model_tier)
        )
        conversation = "\n".join(
            data_block("turn", text, speaker=speaker) for speaker, text in turns
        )
        options = data_block(
            "options",
            f"User's concern: {concern}" if concern else "No specific concern given.",
            relation=req.relation,
            ui_lang=user.ui_locale,
            target_lang=req.target_lang,
        )
        built = build_messages(
            template,
            {
                "options": options,
                # 턴 블록은 이미 이스케이프했으므로 바깥 태그만 직접 붙인다.
                "conversation": f"<conversation>\n{conversation or '(none)'}\n</conversation>",
                "message": data_block("message", message),
            },
        )
        texts = [message, *(text for _, text in turns)]
        if concern:
            texts.append(concern)
        return PreparedCall(
            user_id=user.id,
            kind=TransformKind.REPLY_INTERPRET,
            tier=tier,
            call=LlmCall(
                system=guardrails.with_canary(built.system, self.canary),
                user=built.user,
                output_schema=template.output_schema,
                max_tokens=template.max_tokens,
                effort=template.effort,
            ),
            template=template,
            guard_template=await guardrails.load_guard_template(self.db),
            guard_texts=texts,
            context="\n".join(f"{speaker}: {text}" for speaker, text in turns) or None,
            draft=message,
            source_lang=detect_lang(message),
            target_lang=req.target_lang,
        )

    async def stream(
        self, p: PreparedCall, request_id: str, ui_locale: str
    ) -> AsyncIterator[SseEvent]:
        """meta → analysis → interpretation×N → guide → reply×3 → done."""
        p.request_id = request_id
        yield "meta", {"request_id": request_id, "model_tier": p.tier.value}
        stats = StreamStats()
        parser = IncrementalObjectParser(
            item_keys=frozenset({"interpretations", "suggested_replies"})
        )
        status = LogStatus.SUCCESS
        try:
            guard = guardrails.check(p.guard_texts, template=p.guard_template, llm=self.llm)
            async for chunk in guarded_stream(self.llm, p.tier, p.call, guard, stats):
                for ev in parser.feed(chunk):
                    for out in self._piece(p, ev):
                        yield out
            guardrails.assert_no_canary(parser.text, self.canary)
            try:
                ReplyInterpretOutput.model_validate(json.loads(parser.text))
            except (ValueError, ValidationError) as exc:
                raise LlmOutputInvalidError(log_detail="final_validation") from exc
            if not p.output.get("suggested_replies"):
                raise LlmOutputInvalidError(log_detail="no_safe_replies")
            assert stats.done is not None  # noqa: S101
            yield (
                "done",
                {
                    "disclaimer": DISCLAIMERS.get(ui_locale, DISCLAIMERS["en"]),
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

    def _piece(self, p: PreparedCall, ev: FieldCompleted | ItemCompleted) -> list[SseEvent]:
        guardrails.assert_no_canary(json.dumps(ev.value, ensure_ascii=False), self.canary)
        if isinstance(ev, FieldCompleted):
            if ev.key == "message_emotion":
                emotion = emotion_out(Emotion.model_validate(ev.value)).model_dump()
                p.output["message_emotion"] = emotion
                return [("analysis", {"message_emotion": emotion})]
            if ev.key == "guide":
                p.output["guide"] = Guide.model_validate(ev.value).model_dump()
                return [("guide", p.output["guide"])]
            return []
        if ev.key == "interpretations":
            item = Interpretation.model_validate(ev.value).model_dump()
            p.output.setdefault("interpretations", []).append(item)
            return [("interpretation", {"index": ev.index, **item})]
        if ev.key == "suggested_replies":
            reply = SuggestedReply.model_validate(ev.value)
            if guardrails.is_unsafe_output(reply.text):
                logger.warning("guardrail.unsafe_reply_dropped", extra={"style": reply.style})
                return []
            out = SuggestedReplyOut(**reply.model_dump()).model_dump()
            p.output.setdefault("suggested_replies", []).append(out)
            return [("reply", {"index": ev.index, **out})]
        return []

    async def interpret(
        self, user: User, req: ReplyInterpretRequest, request_id: str
    ) -> ReplyInterpretResponse:
        for attempt in range(2):
            p = await self.prepare(user, req)
            disclaimer = ""
            try:
                async for name, data in self.stream(p, request_id, user.ui_locale):
                    if name == "done":
                        disclaimer = data["disclaimer"]
            except LlmOutputInvalidError:
                if attempt == 0:
                    continue
                raise
            return ReplyInterpretResponse(
                request_id=request_id,
                message_emotion=p.output["message_emotion"],
                interpretations=p.output["interpretations"],
                guide=p.output["guide"],
                suggested_replies=p.output["suggested_replies"],
                disclaimer=disclaimer,
            )
        raise LlmOutputInvalidError(log_detail="unreachable")  # pragma: no cover

    async def _log(self, p: PreparedCall, stats: StreamStats, status: LogStatus) -> None:
        done = stats.done
        emotion = p.output.get("message_emotion") or {}
        await self.log_writer.write(
            LogEntry(
                user_id=p.user_id,
                request_id=p.request_id,
                kind=p.kind,
                status=status,
                model_tier=p.tier,
                model_id=done.model if done else "-",
                prompt_template_id=p.template.id,
                source_lang=p.source_lang,
                target_lang=p.target_lang,
                context=p.context,
                draft=p.draft,
                output=p.output or None,
                emotion_temperature=emotion.get("temperature"),
                guardrail_score=stats.guard.score if stats.guard else None,
                input_tokens=done.input_tokens if done else None,
                output_tokens=done.output_tokens if done else None,
                cached_tokens=done.cached_tokens if done else None,
                ttft_ms=stats.ttft_ms,
                latency_ms=stats.latency_ms,
            )
        )
