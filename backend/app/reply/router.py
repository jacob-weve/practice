from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from app.auth.deps import ActiveUser
from app.core.deps import DbDep, LlmClientDep, RedisDep, SettingsDep
from app.core.sse import sse_response, wants_sse
from app.privacy.log_writer import TransformationLogWriter
from app.reply.schemas import ReplyInterpretRequest, ReplyInterpretResponse
from app.reply.service import ReplyService
from app.tone.router import enforce_user_limit, get_log_writer

router = APIRouter(prefix="/reply", tags=["reply"])


def get_reply_service(
    db: DbDep,
    llm: LlmClientDep,
    settings: SettingsDep,
    log_writer: Annotated[TransformationLogWriter, Depends(get_log_writer)],
) -> ReplyService:
    return ReplyService(db, llm, settings, log_writer)


ReplyServiceDep = Annotated[ReplyService, Depends(get_reply_service)]


@router.post("/interpret", response_model=ReplyInterpretResponse)
async def interpret(
    body: ReplyInterpretRequest,
    request: Request,
    response: Response,
    user: ActiveUser,
    service: ReplyServiceDep,
    redis: RedisDep,
) -> ReplyInterpretResponse | StreamingResponse:
    # 변환과 같은 한도를 공유한다(둘 다 고비용 호출).
    rate = await enforce_user_limit(redis, str(user.id), user.plan, "transform")
    request_id = str(request.state.request_id)
    if wants_sse(request):
        prepared = await service.prepare(user, body)
        return sse_response(
            request, service.stream(prepared, request_id, user.ui_locale), headers=rate.headers()
        )
    response.headers.update(rate.headers())
    return await service.interpret(user, body, request_id)
