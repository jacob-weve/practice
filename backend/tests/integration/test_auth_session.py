import json
import logging

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import REVOKE_QUEUE_KEY
from app.core.config import Settings
from app.db.models import RefreshToken, SocialAccount, User, UserConsent
from tests.fakes import FakeIdP
from tests.integration.test_auth_login import (
    GOOGLE_TOKEN,
    KAKAO_TOKEN,
    REQUIRED,
    apple_web_login,
    oidc_login,
)

MOBILE = {"X-Client-Platform": "android"}


async def mobile_login(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idp: FakeIdP, sub: str = "g-1"
) -> dict[str, str]:
    res = await oidc_login(
        client,
        mock_http,
        idp,
        "google",
        GOOGLE_TOKEN,
        sub,
        claims={"email": "user@example.com", "email_verified": True},
        extra_body={"consents": REQUIRED},
        headers=MOBILE,
    )
    assert res.status_code == 200, res.text
    body: dict[str, str] = res.json()
    return body


async def refresh_mobile(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token}, headers=MOBILE)


# ------------------------------------------------------------------ refresh
async def test_refresh_rotates_and_detects_reuse(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    settings: Settings,
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings.refresh_reuse_grace_seconds = 0
    first = (await mobile_login(client, mock_http, idps["google"]))["refresh_token"]

    rotated = await refresh_mobile(client, first)
    assert rotated.status_code == 200
    second = rotated.json()["refresh_token"]
    assert second != first

    with caplog.at_level(logging.WARNING):
        reused = await refresh_mobile(client, first)
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "AUTH_REFRESH_REUSED"
    assert any(r.getMessage() == "security.refresh_reuse" for r in caplog.records)

    # 재사용이 감지되면 같은 family의 최신 토큰도 폐기된다.
    after = await refresh_mobile(client, second)
    assert after.json()["error"]["code"] == "AUTH_REFRESH_INVALID"
    reasons = (await db.execute(select(RefreshToken.revoked_reason))).scalars().all()
    assert "reuse_detected" in reasons


async def test_concurrent_refresh_within_grace_is_not_reuse(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    first = (await mobile_login(client, mock_http, idps["google"]))["refresh_token"]
    a = await refresh_mobile(client, first)
    b = await refresh_mobile(client, first)  # 경합에서 진 요청 (grace 5초 이내)
    assert a.status_code == b.status_code == 200
    assert a.json()["refresh_token"] != b.json()["refresh_token"]
    assert (await refresh_mobile(client, a.json()["refresh_token"])).status_code == 200


async def test_refresh_token_is_stored_hashed_only(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    db: AsyncSession,
) -> None:
    raw = (await mobile_login(client, mock_http, idps["google"]))["refresh_token"]
    hashes = (await db.execute(select(RefreshToken.token_hash))).scalars().all()
    assert raw not in hashes
    assert all(len(h) == 64 for h in hashes)


async def test_unknown_refresh_token(client: httpx.AsyncClient) -> None:
    res = await refresh_mobile(client, "x" * 43)
    assert res.json()["error"]["code"] == "AUTH_REFRESH_INVALID"


async def test_web_refresh_requires_csrf_header_and_rotates_cookie(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    login = await oidc_login(client, mock_http, idps["google"], "google", GOOGLE_TOKEN, "w")
    old_cookie = login.cookies["ts_rt"]
    client.cookies.set("ts_rt", old_cookie, path="/api/v1/auth")

    blocked = await client.post("/api/v1/auth/refresh")
    assert blocked.json()["error"]["code"] == "AUTH_REFRESH_INVALID"

    ok = await client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "talksoft"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["refresh_token"] is None
    assert ok.cookies["ts_rt"] != old_cookie


# ------------------------------------------------------------ access token
async def test_protected_endpoint_rejects_bad_tokens(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/users/me")
    assert missing.json()["error"]["code"] == "AUTH_TOKEN_INVALID"
    forged = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer a.b.c"})
    assert forged.json()["error"]["code"] == "AUTH_TOKEN_INVALID"


async def test_expired_access_token(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    settings: Settings,
) -> None:
    settings.access_token_ttl_seconds = -1
    access = (await mobile_login(client, mock_http, idps["google"]))["access_token"]
    res = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert res.json()["error"]["code"] == "AUTH_TOKEN_EXPIRED"


async def test_users_me_get_and_patch(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    access = (await mobile_login(client, mock_http, idps["google"]))["access_token"]
    auth = {"Authorization": f"Bearer {access}"}
    me = await client.get("/api/v1/users/me", headers=auth)
    assert me.json()["user"]["email"] == "user@example.com"
    patched = await client.patch(
        "/api/v1/users/me", json={"ui_locale": "en", "display_name": "Liam"}, headers=auth
    )
    assert patched.json()["user"]["ui_locale"] == "en"
    assert patched.json()["user"]["display_name"] == "Liam"
    bad = await client.patch("/api/v1/users/me", json={"plan": "premium"}, headers=auth)
    assert bad.status_code == 400


# ------------------------------------------------------------------ logout
async def test_logout_revokes_family(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    tokens = await mobile_login(client, mock_http, idps["google"])
    res = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}", **MOBILE},
    )
    assert res.status_code == 204
    after = await refresh_mobile(client, tokens["refresh_token"])
    assert after.json()["error"]["code"] == "AUTH_REFRESH_INVALID"


# ---------------------------------------------------------------- linking
async def test_link_second_provider_and_conflict(
    client: httpx.AsyncClient, mock_http: respx.MockRouter, idps: dict[str, FakeIdP]
) -> None:
    owner = await mobile_login(client, mock_http, idps["google"], sub="owner")
    other = await oidc_login(client, mock_http, idps["kakao"], "kakao", KAKAO_TOKEN, "taken")
    assert other.status_code == 200

    from tests.conftest import REDIRECTS
    from tests.fakes import new_verifier, start_authorization

    async def link(sub: str) -> httpx.Response:
        verifier = new_verifier()
        state, nonce = await start_authorization(client, "kakao", REDIRECTS["kakao"], verifier)
        mock_http.post(KAKAO_TOKEN).respond(json={"id_token": idps["kakao"].id_token(sub, nonce)})
        return await client.post(
            "/api/v1/auth/link/kakao",
            json={
                "code": "c",
                "state": state,
                "code_verifier": verifier,
                "redirect_uri": REDIRECTS["kakao"],
            },
            headers={"Authorization": f"Bearer {owner['access_token']}"},
        )

    ok = await link("fresh")
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["linked_providers"] == ["google", "kakao"]

    conflict = await link("taken")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "ACCOUNT_LINK_CONFLICT"


# --------------------------------------------------------------- withdrawal
async def test_delete_user_revokes_apple_and_cascades(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    db: AsyncSession,
) -> None:
    login = await apple_web_login(client, mock_http, idps["apple"], "apple-del")
    access = login.json()["access_token"]
    await client.post(
        "/api/v1/auth/consents",
        json={"consents": REQUIRED},
        headers={"Authorization": f"Bearer {access}"},
    )
    revoke = mock_http.post("https://appleid.apple.com/auth/revoke").respond(200)

    res = await client.delete("/api/v1/users/me", headers={"Authorization": f"Bearer {access}"})
    assert res.status_code == 204
    assert revoke.call_count == 1
    assert b"token=apple-rt" in revoke.calls[0].request.content
    for model in (User, SocialAccount, RefreshToken, UserConsent):
        assert await db.scalar(select(func.count()).select_from(model)) == 0


async def test_delete_user_enqueues_revoke_on_provider_failure(
    app: FastAPI,
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    db: AsyncSession,
) -> None:
    login = await oidc_login(client, mock_http, idps["kakao"], "kakao", KAKAO_TOKEN, "k-del")
    mock_http.post("https://kapi.kakao.com/v1/user/unlink").respond(500)
    res = await client.delete(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert res.status_code == 204
    assert await db.scalar(select(func.count()).select_from(User)) == 0
    queued = await app.state.redis.lrange(REVOKE_QUEUE_KEY, 0, -1)
    assert [json.loads(q)["provider_user_id"] for q in queued] == ["k-del"]


async def test_apple_account_delete_notification_removes_user(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    db: AsyncSession,
) -> None:
    await apple_web_login(client, mock_http, idps["apple"], "apple-n")
    events = json.dumps({"type": "account-delete", "sub": "apple-n", "event_time": 1})
    payload = idps["apple"].id_token("ignored", None, events=events, sub=None, exp=None)
    res = await client.post("/api/v1/auth/apple/notifications", json={"payload": payload})
    assert res.status_code == 200, res.text
    assert await db.scalar(select(func.count()).select_from(User)) == 0


# ----------------------------------------------------------- log hygiene
async def test_logs_never_contain_tokens_or_emails(
    client: httpx.AsyncClient,
    mock_http: respx.MockRouter,
    idps: dict[str, FakeIdP],
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.core.logging import JsonFormatter

    with caplog.at_level(logging.DEBUG):
        tokens = await mobile_login(client, mock_http, idps["google"])
        await refresh_mobile(client, tokens["refresh_token"])
        await refresh_mobile(client, "y" * 43)
        await client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )

    formatter = JsonFormatter()
    output = "\n".join(formatter.format(r) for r in caplog.records)
    assert caplog.records  # 로그가 실제로 남았는지 확인
    for secret in (
        tokens["access_token"],
        tokens["refresh_token"],
        "user@example.com",
        "auth-code",
    ):
        assert secret not in output
