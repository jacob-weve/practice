from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update

from app.auth.deps import ActiveUser
from app.core.deps import DbDep
from app.db.models import TransformationLog

router = APIRouter(tags=["feedback"])

VariantKind = Literal["primary", "softer", "concise", "confirm", "empathize", "light_shift"]


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    action: Literal["copied", "shared", "thumbs_up", "thumbs_down"]
    variant_kind: VariantKind | None = None
    reason: Literal["intent_changed", "too_formal", "too_casual", "unnatural", "other"] | None = (
        None
    )


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(body: FeedbackRequest, user: ActiveUser, db: DbDep) -> Response:
    """결과 채택 신호만 남긴다(원문 없음). 본인 요청의 로그에만 기록된다."""
    if body.action in ("copied", "shared") and body.variant_kind:
        await db.execute(
            update(TransformationLog)
            .where(
                TransformationLog.request_id == body.request_id,
                TransformationLog.user_id == user.id,
            )
            .values(selected_variant=body.variant_kind)
        )
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
