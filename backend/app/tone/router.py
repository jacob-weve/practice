from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from app.auth.deps import ActiveUser
from app.core.deps import DbDep, LlmClientDep, RedisDep, SettingsDep
from app.core.rate_limit import RateWindow, enforce_fixed_window
from app.core.sse import sse_response, wants_sse
from app.privacy.log_writer import TransformationLogWriter
from app.tone.schemas import (
    ToneAnalyzeRequest,
    ToneAnalyzeResponse,
    ToneOptionsResponse,
    ToneTransformRequest,
    ToneTransformResponse,
)
from app.tone.service import ToneService

router = APIRouter(prefix="/tone", tags=["tone"])

# (분당, 일일) 한도 — API_SPEC §5
LIMITS = {
    "free": {"transform": (30, 300), "analyze": (60, 1000)},
    "premium": {"transform": (60, 3000), "analyze": (120, 5000)},
}


def get_log_writer(request: Request) -> TransformationLogWriter:
    writer: TransformationLogWriter = request.app.state.log_writer
    return writer


def get_tone_service(
    db: DbDep,
    llm: LlmClientDep,
    settings: SettingsDep,
    log_writer: Annotated[TransformationLogWriter, Depends(get_log_writer)],
) -> ToneService:
    return ToneService(db, llm, settings, log_writer)


ToneServiceDep = Annotated[ToneService, Depends(get_tone_service)]


async def enforce_user_limit(redis: RedisDep, user_id: str, plan: str, bucket: str) -> RateWindow:
    per_minute, per_day = LIMITS.get(plan, LIMITS["free"])[bucket]
    await enforce_fixed_window(redis, f"{bucket}:d:{user_id}", per_day, 86_400)
    return await enforce_fixed_window(redis, f"{bucket}:m:{user_id}", per_minute, 60)


@router.get("/options", response_model=ToneOptionsResponse)
async def options(user: ActiveUser, service: ToneServiceDep) -> ToneOptionsResponse:
    return await service.options(user.ui_locale)


@router.post("/transform", response_model=ToneTransformResponse)
async def transform(
    body: ToneTransformRequest,
    request: Request,
    response: Response,
    user: ActiveUser,
    service: ToneServiceDep,
    redis: RedisDep,
) -> ToneTransformResponse | StreamingResponse:
    rate = await enforce_user_limit(redis, str(user.id), user.plan, "transform")
    request_id = str(request.state.request_id)
    if wants_sse(request):
        # 입력 검증·템플릿 조회 오류는 스트림을 열기 전에 일반 JSON 에러로 돌려준다.
        prepared = await service.prepare_transform(user, body)
        return sse_response(
            request, service.stream_transform(prepared, request_id), headers=rate.headers()
        )
    response.headers.update(rate.headers())
    return await service.transform(user, body, request_id)


@router.post("/analyze", response_model=ToneAnalyzeResponse)
async def analyze(
    body: ToneAnalyzeRequest,
    request: Request,
    response: Response,
    user: ActiveUser,
    service: ToneServiceDep,
    redis: RedisDep,
) -> ToneAnalyzeResponse:
    rate = await enforce_user_limit(redis, str(user.id), user.plan, "analyze")
    response.headers.update(rate.headers())
    return await service.analyze(user, body, str(request.state.request_id))
