import uuid
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ConsentType, SocialProvider, UserStatus

PKCE_PATTERN = r"^[A-Za-z0-9\-._~]+$"
CHALLENGE_PATTERN = r"^[A-Za-z0-9_-]{43}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthorizeResponse(StrictModel):
    authorize_url: str
    state: str
    expires_in: int


class ConsentItem(StrictModel):
    type: ConsentType
    version: str = Field(min_length=1, max_length=20)
    agreed: bool


class AppleName(BaseModel):
    firstName: str | None = Field(default=None, max_length=50)  # noqa: N815 (애플 응답 형식)
    lastName: str | None = Field(default=None, max_length=50)  # noqa: N815


class AppleUser(BaseModel):
    name: AppleName | None = None


class SocialLoginRequest(StrictModel):
    code: str | None = Field(default=None, min_length=1, max_length=2048)
    # 애플 웹 form_post 콜백 후 프론트로 넘겨주는 1회용 교환 코드. code 대신 쓴다.
    handoff: str | None = Field(default=None, min_length=16, max_length=128)
    state: str | None = Field(default=None, min_length=16, max_length=128)
    code_verifier: str = Field(min_length=43, max_length=128, pattern=PKCE_PATTERN)
    redirect_uri: str = Field(max_length=2048)
    apple_user: AppleUser | None = None
    consents: list[ConsentItem] = Field(default_factory=list, max_length=10)
    device_info: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _code_or_handoff(self) -> Self:
        if (self.code is None) == (self.handoff is None):
            raise ValueError("exactly one of code or handoff is required")
        if self.code is not None and self.state is None:
            raise ValueError("state is required with code")
        return self


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class LogoutRequest(StrictModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=256)


class ConsentSubmitRequest(StrictModel):
    consents: list[ConsentItem] = Field(min_length=1, max_length=10)


class RequiredConsent(StrictModel):
    type: ConsentType
    version: str
    url: str | None


class UserProfile(StrictModel):
    id: uuid.UUID
    display_name: str | None
    email: str | None
    is_private_email: bool
    status: UserStatus
    ui_locale: str
    default_target_lang: str
    plan: str
    linked_providers: list[SocialProvider]


class AuthTokenResponse(StrictModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int
    refresh_token: str | None = None
    refresh_expires_in: int | None = None
    is_new_user: bool
    user: UserProfile
    required_consents: list[RequiredConsent] = Field(default_factory=list)


class TokenRefreshResponse(StrictModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int
    refresh_token: str | None = None
    refresh_expires_in: int


class UserResponse(StrictModel):
    user: UserProfile
