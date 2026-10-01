from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import Field

from app.auth.deps import AuthServiceDep, CurrentUser
from app.auth.schemas import StrictModel, UserResponse
from app.auth.service import to_profile
from app.core.deps import DbDep, SettingsDep

router = APIRouter(prefix="/users", tags=["users"])

Locale = Literal["ko", "en", "ja"]


class UserUpdateRequest(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    ui_locale: Locale | None = None
    default_target_lang: Locale | None = None


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser) -> UserResponse:
    return UserResponse(user=to_profile(user))


@router.patch("/me", response_model=UserResponse)
async def update_me(body: UserUpdateRequest, user: CurrentUser, db: DbDep) -> UserResponse:
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    await db.commit()
    return UserResponse(user=to_profile(user))


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: CurrentUser, service: AuthServiceDep, settings: SettingsDep) -> Response:
    await service.delete_user(user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.refresh_cookie_name, path=settings.refresh_cookie_path)
    return response
