import logging
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.i18n import negotiate_locale, translate_error

logger = logging.getLogger(__name__)


class AppError(Exception):
    code: ClassVar[str] = "INTERNAL_ERROR"
    http_status: ClassVar[int] = 500

    def __init__(self, log_detail: str | None = None, details: dict[str, Any] | None = None):
        # log_detail은 서버 로그에만 남긴다. 응답에는 code와 번역된 일반 메시지만 나간다.
        super().__init__(log_detail or self.code)
        self.log_detail = log_detail
        self.details = details or {}
        self.headers: dict[str, str] = {}


class ValidationAppError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 400


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    http_status = 429

    def __init__(self, retry_after: int):
        super().__init__(details={"retry_after": retry_after})
        self.headers = {"Retry-After": str(retry_after)}


class AuthError(AppError):
    code = "AUTH_ERROR"
    http_status = 401


class UnsupportedProviderError(AuthError):
    code = "AUTH_UNSUPPORTED_PROVIDER"
    http_status = 400


class InvalidRedirectUriError(AuthError):
    code = "AUTH_INVALID_REDIRECT_URI"
    http_status = 400


class InvalidStateError(AuthError):
    code = "AUTH_INVALID_STATE"
    http_status = 400


class PKCEMismatchError(AuthError):
    code = "AUTH_PKCE_MISMATCH"
    http_status = 400


class ProviderDeniedError(AuthError):
    code = "AUTH_PROVIDER_DENIED"
    http_status = 401


class IdTokenInvalidError(AuthError):
    code = "AUTH_ID_TOKEN_INVALID"
    http_status = 401


class TokenExpiredError(AuthError):
    code = "AUTH_TOKEN_EXPIRED"
    http_status = 401


class TokenInvalidError(AuthError):
    code = "AUTH_TOKEN_INVALID"
    http_status = 401


class RefreshInvalidError(AuthError):
    code = "AUTH_REFRESH_INVALID"
    http_status = 401


class RefreshReusedError(AuthError):
    code = "AUTH_REFRESH_REUSED"
    http_status = 401


class ProviderUnavailableError(AuthError):
    code = "AUTH_PROVIDER_UNAVAILABLE"
    http_status = 503


class ConsentRequiredError(AppError):
    code = "CONSENT_REQUIRED"
    http_status = 403


class AccountSuspendedError(AppError):
    code = "ACCOUNT_SUSPENDED"
    http_status = 403


class AccountLinkConflictError(AppError):
    code = "ACCOUNT_LINK_CONFLICT"
    http_status = 409


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def error_response(
    request: Request,
    code: str,
    status: int,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    locale = negotiate_locale(request.headers.get("accept-language"))
    body = {
        "error": {
            "code": code,
            "message": translate_error(code, locale),
            "request_id": _request_id(request),
            "details": details or {},
        }
    }
    return JSONResponse(status_code=status, content=body, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        log = logger.warning if exc.http_status < 500 else logger.error
        log("app_error", extra={"code": exc.code, "detail": exc.log_detail})
        return error_response(request, exc.code, exc.http_status, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 입력값(input)은 사용자 원문일 수 있으므로 응답·로그에 넣지 않고 위치와 유형만 돌려준다.
        fields = [
            {"loc": [str(p) for p in err.get("loc", ())], "type": err.get("type")}
            for err in exc.errors()
        ]
        return error_response(request, "VALIDATION_ERROR", 400, {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return error_response(request, code, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error")
        return error_response(request, "INTERNAL_ERROR", 500)
