import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import SocialAccount, User
from tests.conftest import REDIRECTS
from tests.fakes import FakeIdP, new_verifier, start_authorization

GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
KAKAO_TOKEN = "https://kauth.kakao.com/oauth/token"
NAVER_TOKEN = "https://nid.naver.com/oauth2.0/token"
NAVER_PROFILE = "https://openapi.naver.com/v1/nid/me"
APPLE_TOKEN = "https://appleid.apple.com/auth/token"

REQUIRED = [
    {"type": "terms_of_service", "version": "2026-10-01", "agreed": True},
    {"type": "privacy_policy", "version": "2026-10-01", "agreed": True},
    {"type": "age_over_14", "version": "2026-10-01", "agreed": True},
]


async def oidc_login(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idp: FakeIdP,
    provider: str,
    token_url: str,
    sub: str,
    *,
    claims: dict[str, Any] | None = None,
    extra_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    verifier = new_verifier()
    state, nonce = await start_authorization(client, provider, REDIRECTS[provider], verifier)
    id_token = idp.id_token(sub, nonce, **(claims or {}))
    mock_http.post(token_url).respond(json={"id_token": id_token, "access_token": "at"})
    body = {
        "code": "auth-code",
        "state": state,
        "code_verifier": verifier,
        "redirect_uri": REDIRECTS[provider],
        **(extra_body or {}),
    }
    return await client.post(f"/api/v1/auth/login/{provider}", json=body, headers=headers)


# ------------------------------------------------------------------ authorize
async def test_authorize_builds_provider_url_with_pkce(client: httpx.AsyncClient) -> None:
    state, nonce = await start_authorization(client, "google", REDIRECTS["google"], new_verifier())
    assert len(state) >= 16 and nonce


async def test_authorize_apple_uses_form_post(client: httpx.AsyncClient) -> None:
    res = await client.get(
        "/api/v1/auth/authorize/apple",
        params={
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
            "redirect_uri": REDIRECTS["apple"],
        },
    )
    query = parse_qs(urlparse(res.json()["authorize_url"]).query)
    assert query["response_mode"] == ["form_post"]


@pytest.mark.parametrize(
    ("provider", "redirect", "code"),
    [
        ("facebook", REDIRECTS["google"], "AUTH_UNSUPPORTED_PROVIDER"),
        ("google", "https://evil.example/cb", "AUTH_INVALID_REDIRECT_URI"),
    ],
)
async def test_authorize_rejects_bad_input(
    client: httpx.AsyncClient, provider: str, redirect: str, code: str
) -> None:
    res = await client.get(
        f"/api/v1/auth/authorize/{provider}",
        params={
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
            "redirect_uri": redirect,
        },
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == code


# ---------------------------------------------------------------------- login
async def test_google_signup_is_pending_consent_and_sets_cookie(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    res = await oidc_login(
        client,
        mock_http,
        idps["google"],
        "google",
        GOOGLE_TOKEN,
        "g-1",
        claims={"email": "jieun@example.com", "email_verified": True, "name": "지은"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["is_new_user"] is True
    assert body["refresh_token"] is None  # 웹은 쿠키로만 전달
    assert body["user"]["status"] == "pending_consent"
    assert body["user"]["display_name"] == "지은"
    assert body["user"]["linked_providers"] == ["google"]
    assert {c["type"] for c in body["required_consents"]} == {
        "terms_of_service",
        "privacy_policy",
        "age_over_14",
    }
    cookie = res.headers["set-cookie"]
    assert "ts_rt=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie

    # 같은 사용자의 두 번째 로그인은 신규 가입이 아니다.
    again = await oidc_login(client, mock_http, idps["google"], "google", GOOGLE_TOKEN, "g-1")
    assert again.json()["is_new_user"] is False
    assert again.json()["user"]["id"] == body["user"]["id"]


async def test_consents_activate_user(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    login = await oidc_login(client, mock_http, idps["google"], "google", GOOGLE_TOKEN, "g-2")
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    res = await client.post("/api/v1/auth/consents", json={"consents": REQUIRED}, headers=auth)
    assert res.status_code == 200
    assert res.json()["user"]["status"] == "active"

    # 필수 동의 철회 시 다시 pending_consent
    revoke = [{"type": "privacy_policy", "version": "2026-10-01", "agreed": False}]
    res = await client.post("/api/v1/auth/consents", json={"consents": revoke}, headers=auth)
    assert res.json()["user"]["status"] == "pending_consent"


async def test_kakao_login_with_consents_is_active_and_mobile_gets_refresh_in_body(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    res = await oidc_login(
        client,
        mock_http,
        idps["kakao"],
        "kakao",
        KAKAO_TOKEN,
        "12345",
        claims={"nickname": "도윤", "email": "doyoon@example.com"},
        extra_body={"consents": REQUIRED},
        headers={"X-Client-Platform": "ios"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user"]["status"] == "active"
    assert body["required_consents"] == []
    assert body["refresh_token"]
    assert "set-cookie" not in res.headers


async def test_naver_login_uses_profile_api_and_retries_5xx(
    client: httpx.AsyncClient, mock_http: respx.MockRouter
) -> None:
    verifier = new_verifier()
    state, nonce = await start_authorization(client, "naver", REDIRECTS["naver"], verifier)
    assert nonce is None  # 네이버는 OIDC 미지원
    mock_http.post(NAVER_TOKEN).respond(json={"access_token": "naver-at"})
    profile = mock_http.get(NAVER_PROFILE)
    profile.side_effect = [
        httpx.Response(503),
        httpx.Response(
            200,
            json={"resultcode": "00", "response": {"id": "nv-1", "nickname": "수진"}},
        ),
    ]
    res = await client.post(
        "/api/v1/auth/login/naver",
        json={
            "code": "c",
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": REDIRECTS["naver"],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["user"]["display_name"] == "수진"
    assert res.json()["user"]["email"] is None
    assert profile.call_count == 2


async def test_same_email_on_different_providers_is_not_merged(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    db: AsyncSession,
) -> None:
    email = {"email": "same@example.com", "email_verified": True}
    a = await oidc_login(
        client, mock_http, idps["google"], "google", GOOGLE_TOKEN, "g", claims=email
    )
    b = await oidc_login(client, mock_http, idps["kakao"], "kakao", KAKAO_TOKEN, "k", claims=email)
    assert a.json()["user"]["id"] != b.json()["user"]["id"]
    assert await db.scalar(select(func.count()).select_from(User)) == 2


# ------------------------------------------------------- security rejections
async def test_state_is_single_use(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    verifier = new_verifier()
    state, nonce = await start_authorization(client, "google", REDIRECTS["google"], verifier)
    mock_http.post(GOOGLE_TOKEN).respond(json={"id_token": idps["google"].id_token("g", nonce)})
    body = {
        "code": "c",
        "state": state,
        "code_verifier": verifier,
        "redirect_uri": REDIRECTS["google"],
    }
    assert (await client.post("/api/v1/auth/login/google", json=body)).status_code == 200
    replay = await client.post("/api/v1/auth/login/google", json=body)
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "AUTH_INVALID_STATE"


async def test_pkce_mismatch_is_rejected_and_state_is_burned(
    client: httpx.AsyncClient, mock_http: respx.MockRouter
) -> None:
    verifier = new_verifier()
    state, _ = await start_authorization(client, "google", REDIRECTS["google"], verifier)
    token_route = mock_http.post(GOOGLE_TOKEN)
    body = {
        "code": "c",
        "state": state,
        "code_verifier": new_verifier(),
        "redirect_uri": REDIRECTS["google"],
    }
    res = await client.post("/api/v1/auth/login/google", json=body)
    assert res.json()["error"]["code"] == "AUTH_PKCE_MISMATCH"
    assert token_route.call_count == 0  # 제공자에 코드를 보내기 전에 막는다
    body["code_verifier"] = verifier
    res = await client.post("/api/v1/auth/login/google", json=body)
    assert res.json()["error"]["code"] == "AUTH_INVALID_STATE"


async def test_state_from_other_provider_is_rejected(client: httpx.AsyncClient) -> None:
    verifier = new_verifier()
    state, _ = await start_authorization(client, "google", REDIRECTS["google"], verifier)
    res = await client.post(
        "/api/v1/auth/login/kakao",
        json={
            "code": "c",
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": REDIRECTS["google"],
        },
    )
    assert res.json()["error"]["code"] == "AUTH_INVALID_STATE"


@pytest.mark.parametrize(
    "claims",
    [
        {"nonce": "wrong-nonce"},
        {"aud": "someone-else"},
        {"iss": "https://evil.example"},
        {"exp": 1, "iat": 0},
    ],
    ids=["nonce", "aud", "iss", "expired"],
)
async def test_invalid_id_token_is_rejected_without_leaking_reason(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    claims: dict[str, Any],
) -> None:
    res = await oidc_login(
        client, mock_http, idps["google"], "google", GOOGLE_TOKEN, "g", claims=claims
    )
    assert res.status_code == 401
    error = res.json()["error"]
    assert error["code"] == "AUTH_ID_TOKEN_INVALID"
    assert error["details"] == {}


async def test_id_token_signed_by_unknown_key_is_rejected(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    attacker = FakeIdP("https://accounts.google.com", "google-client", kid="evil")
    res = await oidc_login(client, mock_http, attacker, "google", GOOGLE_TOKEN, "g")
    assert res.json()["error"]["code"] == "AUTH_ID_TOKEN_INVALID"


@pytest.mark.parametrize(
    ("response", "status", "code"),
    [
        (httpx.Response(500), 503, "AUTH_PROVIDER_UNAVAILABLE"),
        (httpx.Response(400, json={"error": "invalid_grant"}), 401, "AUTH_PROVIDER_DENIED"),
    ],
)
async def test_token_exchange_failures(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    response: httpx.Response,
    status: int,
    code: str,
) -> None:
    verifier = new_verifier()
    state, _ = await start_authorization(client, "google", REDIRECTS["google"], verifier)
    route = mock_http.post(GOOGLE_TOKEN).mock(return_value=response)
    res = await client.post(
        "/api/v1/auth/login/google",
        json={
            "code": "c",
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": REDIRECTS["google"],
        },
    )
    assert res.status_code == status
    assert res.json()["error"]["code"] == code
    assert route.call_count == 1  # 인가 코드는 1회용이라 재시도하지 않는다


async def test_login_requires_code_or_handoff(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/login/google",
        json={"code_verifier": new_verifier(), "redirect_uri": REDIRECTS["google"]},
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_auth_rate_limit(client: httpx.AsyncClient) -> None:
    params = {
        "code_challenge": "a" * 43,
        "code_challenge_method": "S256",
        "redirect_uri": REDIRECTS["google"],
    }
    codes = [
        (await client.get("/api/v1/auth/authorize/google", params=params)).status_code
        for _ in range(21)
    ]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429


# ---------------------------------------------------------------------- apple
async def apple_web_login(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idp: FakeIdP,
    sub: str,
    *,
    claims: dict[str, Any] | None = None,
    user_json: dict[str, Any] | None = None,
    refresh_token: str | None = "apple-rt",
) -> httpx.Response:
    verifier = new_verifier()
    state, nonce = await start_authorization(client, "apple", REDIRECTS["apple"], verifier)
    form = {"code": "apple-code", "state": state}
    if user_json:
        form["user"] = json.dumps(user_json)
    callback = await client.post("/api/v1/auth/callback/apple", data=form)
    assert callback.status_code == 303
    location = urlparse(callback.headers["location"])
    assert location.path == "/auth/callback/apple"
    handoff = parse_qs(location.query)["handoff"][0]

    token_body = {"id_token": idp.id_token(sub, nonce, **(claims or {}))}
    if refresh_token:
        token_body["refresh_token"] = refresh_token
    mock_http.post(APPLE_TOKEN).respond(json=token_body)
    return await client.post(
        "/api/v1/auth/login/apple",
        json={"handoff": handoff, "code_verifier": verifier, "redirect_uri": REDIRECTS["apple"]},
    )


async def test_apple_private_relay_and_first_time_name(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    db: AsyncSession,
) -> None:
    res = await apple_web_login(
        client,
        mock_http,
        idps["apple"],
        "apple-1",
        claims={
            "email": "x7k2@privaterelay.appleid.com",
            "email_verified": "true",
            "is_private_email": "true",
        },
        user_json={"name": {"firstName": "지은", "lastName": "김"}},
    )
    assert res.status_code == 200, res.text
    user = res.json()["user"]
    assert user["email"] == "x7k2@privaterelay.appleid.com"
    assert user["is_private_email"] is True
    assert user["display_name"] == "지은 김"

    account = await db.scalar(
        select(SocialAccount).where(SocialAccount.provider_user_id == "apple-1")
    )
    assert account is not None
    assert account.email_verified is True
    assert account.provider_refresh_token_enc is not None
    assert b"apple-rt" not in account.provider_refresh_token_enc  # 평문 저장 금지

    # 두 번째 로그인에는 이름이 오지 않아도 기존 이름이 유지된다.
    again = await apple_web_login(client, mock_http, idps["apple"], "apple-1")
    assert again.json()["user"]["display_name"] == "지은 김"


async def test_apple_signup_without_email(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    res = await apple_web_login(client, mock_http, idps["apple"], "apple-2", refresh_token=None)
    assert res.status_code == 200, res.text
    assert res.json()["user"]["email"] is None


async def test_apple_handoff_is_single_use(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    verifier = new_verifier()
    state, nonce = await start_authorization(client, "apple", REDIRECTS["apple"], verifier)
    callback = await client.post("/api/v1/auth/callback/apple", data={"code": "c", "state": state})
    handoff = parse_qs(urlparse(callback.headers["location"]).query)["handoff"][0]
    mock_http.post(APPLE_TOKEN).respond(json={"id_token": idps["apple"].id_token("a", nonce)})
    body = {"handoff": handoff, "code_verifier": verifier, "redirect_uri": REDIRECTS["apple"]}
    assert (await client.post("/api/v1/auth/login/apple", json=body)).status_code == 200
    replay = await client.post("/api/v1/auth/login/apple", json=body)
    assert replay.json()["error"]["code"] == "AUTH_INVALID_STATE"


async def test_apple_callback_cancelled_redirects_with_error(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/callback/apple", data={"error": "user_cancelled_authorize"}
    )
    assert res.status_code == 303
    assert "error=access_denied" in res.headers["location"]


async def test_apple_client_secret_is_es256_jwt(settings: Settings) -> None:
    import jwt as pyjwt

    from app.auth.providers.apple import AppleProvider

    secret = AppleProvider(settings, httpx.AsyncClient(), None).client_secret()  # type: ignore[arg-type]
    header = pyjwt.get_unverified_header(secret)
    claims = pyjwt.decode(secret, options={"verify_signature": False})
    assert header == {"alg": "ES256", "kid": "KEY1234567", "typ": "JWT"}
    assert claims["iss"] == "TEAM123456"
    assert claims["sub"] == "app.talksoft.web"
    assert claims["aud"] == "https://appleid.apple.com"
    assert claims["exp"] - claims["iat"] <= 15777000  # 애플 최대 6개월
