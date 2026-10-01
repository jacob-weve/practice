from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, Form, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.auth.deps import AuthServiceDep, CurrentUser, auth_rate_limit
from app.auth.providers import parse_provider
from app.auth.schemas import (
    CHALLENGE_PATTERN,
    AuthorizeResponse,
    AuthTokenResponse,
    ConsentListResponse,
    ConsentState,
    ConsentSubmitRequest,
    LogoutRequest,
    RefreshRequest,
    SocialLoginRequest,
    TokenRefreshResponse,
    UserResponse,
)
from app.auth.service import to_profile
from app.core.config import Settings
from app.core.deps import SettingsDep
from app.core.errors import RefreshInvalidError, ValidationAppError

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(auth_rate_limit)])

MOBILE_PLATFORMS = {"ios", "android"}
CSRF_HEADER_VALUE = "talksoft"


def _is_mobile(request: Request) -> bool:
    return request.headers.get("x-client-platform", "web").lower() in MOBILE_PLATFORMS


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.refresh_cookie_name,
        token,
        max_age=settings.refresh_token_ttl_seconds,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


@router.get("/authorize/{provider}", response_model=AuthorizeResponse)
async def authorize(
    provider: str,
    service: AuthServiceDep,
    settings: SettingsDep,
    code_challenge: Annotated[str, Query(pattern=CHALLENGE_PATTERN)],
    code_challenge_method: Annotated[Literal["S256"], Query()],
    redirect_uri: Annotated[str, Query(max_length=2048)],
) -> AuthorizeResponse:
    url, state = await service.authorize(parse_provider(provider), code_challenge, redirect_uri)
    return AuthorizeResponse(
        authorize_url=url, state=state, expires_in=settings.oauth_state_ttl_seconds
    )


@router.post("/login/{provider}", response_model=AuthTokenResponse)
async def login(
    provider: str,
    body: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AuthTokenResponse:
    result = await service.login(parse_provider(provider), body)
    mobile = _is_mobile(request)
    if not mobile:
        _set_refresh_cookie(response, result.tokens.refresh_token, settings)
    return AuthTokenResponse(
        access_token=result.tokens.access_token,
        expires_in=settings.access_token_ttl_seconds,
        refresh_token=result.tokens.refresh_token if mobile else None,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
        is_new_user=result.is_new_user,
        user=to_profile(result.user),
        required_consents=await service.missing_required_consents(result.user.id),
    )


@router.post("/callback/apple", include_in_schema=False)
async def apple_callback(
    service: AuthServiceDep,
    settings: SettingsDep,
    code: Annotated[str | None, Form(max_length=2048)] = None,
    state: Annotated[str | None, Form(max_length=128)] = None,
    user: Annotated[str | None, Form(max_length=1024)] = None,
    error: Annotated[str | None, Form(max_length=100)] = None,
) -> RedirectResponse:
    """애플 웹 form_post 콜백. 인가 코드를 1회용 handoff 키로 바꿔 프론트로 넘긴다."""
    target = f"{settings.web_base_url}/auth/callback/apple"
    if error or not code or not state:
        query = urlencode({"error": "access_denied" if error else "invalid_request"})
        return RedirectResponse(f"{target}?{query}", status_code=status.HTTP_303_SEE_OTHER)
    handoff = await service.save_apple_handoff(code, state, user)
    return RedirectResponse(
        f"{target}?{urlencode({'handoff': handoff})}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    body: Annotated[RefreshRequest | None, Body()] = None,
) -> TokenRefreshResponse:
    mobile = _is_mobile(request)
    if mobile:
        if body is None:
            raise ValidationAppError(log_detail="refresh_token_missing")
        raw = body.refresh_token
    else:
        # 쿠키 기반 요청은 커스텀 헤더를 요구해 교차 사이트 요청(CSRF)을 막는다.
        if request.headers.get("x-requested-with") != CSRF_HEADER_VALUE:
            raise RefreshInvalidError(log_detail="csrf_header_missing")
        cookie = request.cookies.get(settings.refresh_cookie_name)
        if not cookie:
            raise RefreshInvalidError(log_detail="cookie_missing")
        raw = cookie

    try:
        issued = await service.tokens.rotate(raw)
    except RefreshInvalidError:
        if not mobile:
            _clear_refresh_cookie(response, settings)
        raise
    if not mobile:
        _set_refresh_cookie(response, issued.refresh_token, settings)
    return TokenRefreshResponse(
        access_token=issued.access_token,
        expires_in=settings.access_token_ttl_seconds,
        refresh_token=issued.refresh_token if mobile else None,
        refresh_expires_in=settings.refresh_token_ttl_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user: CurrentUser,
    service: AuthServiceDep,
    settings: SettingsDep,
    body: Annotated[LogoutRequest | None, Body()] = None,
) -> Response:
    raw = body.refresh_token if body else request.cookies.get(settings.refresh_cookie_name)
    if raw:
        await service.tokens.revoke_by_raw(raw, user.id, "logout")
    else:
        await service.tokens.revoke_all(user.id, "logout")
    await service.db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get("/consents", response_model=ConsentListResponse)
async def list_consents(user: CurrentUser, service: AuthServiceDep) -> ConsentListResponse:
    latest = await service.latest_consents(user.id)
    return ConsentListResponse(
        consents=[
            ConsentState(type=row.consent_type, version=row.version, agreed=row.agreed)
            for row in latest.values()
        ]
    )


@router.post("/consents", response_model=UserResponse)
async def submit_consents(
    body: ConsentSubmitRequest, user: CurrentUser, service: AuthServiceDep
) -> UserResponse:
    updated = await service.submit_consents(user, body.consents)
    return UserResponse(user=to_profile(updated))


@router.post("/link/{provider}", response_model=UserResponse)
async def link_provider(
    provider: str, body: SocialLoginRequest, user: CurrentUser, service: AuthServiceDep
) -> UserResponse:
    updated = await service.link(user, parse_provider(provider), body)
    return UserResponse(user=to_profile(updated))


@router.post("/apple/notifications", status_code=status.HTTP_200_OK)
async def apple_notifications(
    service: AuthServiceDep, payload: Annotated[str, Body(embed=True, max_length=8192)]
) -> dict[str, str]:
    await service.handle_apple_notification(payload)
    return {"status": "ok"}
