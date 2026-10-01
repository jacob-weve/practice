from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.providers.apple import AppleProvider
from app.core.config import Settings
from app.core.security import create_access_token
from app.db.base import Base
from app.db.models import ConsentType, User, UserConsent, UserStatus
from app.main import create_app
from seeds.apply import apply_seeds
from tests.fakes import (
    DEFAULT_LLM_RESPONSES,
    FakeIdP,
    FakeLlmProvider,
    aes_key_b64,
    ec_private_pem,
    rsa_pem_pair,
)

WEB = "http://localhost:3000"
REDIRECTS = {
    "kakao": f"{WEB}/auth/callback/kakao",
    "google": f"{WEB}/auth/callback/google",
    "naver": f"{WEB}/auth/callback/naver",
    "apple": "http://localhost:8000/api/v1/auth/callback/apple",
}

_JWT_PRIVATE, _JWT_PUBLIC = rsa_pem_pair()
_APPLE_KEY = ec_private_pem()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        web_base_url=WEB,
        cors_origins=[WEB],
        oauth_redirect_uris=list(REDIRECTS.values()),
        jwt_private_key=SecretStr(_JWT_PRIVATE),
        jwt_public_key=_JWT_PUBLIC,
        data_encryption_key=SecretStr(aes_key_b64()),
        llm_canary_token=SecretStr("CANARY-7f3a"),
        cookie_secure=False,
        kakao_client_id="kakao-client",
        kakao_admin_key=SecretStr("kakao-admin"),
        google_client_id="google-client",
        google_client_secret=SecretStr("google-secret"),
        naver_client_id="naver-client",
        naver_client_secret=SecretStr("naver-secret"),
        apple_client_id="app.talksoft.web",
        apple_team_id="TEAM123456",
        apple_key_id="KEY1234567",
        apple_private_key=SecretStr(_APPLE_KEY),
    )


@pytest.fixture
def llm() -> FakeLlmProvider:
    return FakeLlmProvider(by_template=dict(DEFAULT_LLM_RESPONSES))


@pytest.fixture
async def app(settings: Settings, llm: FakeLlmProvider) -> AsyncIterator[FastAPI]:
    AppleProvider._cached_secret = None
    application = create_app(
        settings, redis=FakeAsyncRedis(decode_responses=True), llm_provider=llm
    )
    async with application.router.lifespan_context(application):
        async with application.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with application.state.sessionmaker() as session:
            await apply_seeds(session)
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


@pytest.fixture
def mock_http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def idps(settings: Settings, mock_http: respx.MockRouter) -> dict[str, FakeIdP]:
    fakes = {
        "kakao": FakeIdP("https://kauth.kakao.com", settings.kakao_client_id),
        "google": FakeIdP("https://accounts.google.com", settings.google_client_id),
        "apple": FakeIdP("https://appleid.apple.com", settings.apple_client_id),
    }
    mock_http.get("https://kauth.kakao.com/.well-known/jwks.json").respond(
        json=fakes["kakao"].jwks()
    )
    mock_http.get("https://www.googleapis.com/oauth2/v3/certs").respond(json=fakes["google"].jwks())
    mock_http.get("https://appleid.apple.com/auth/keys").respond(json=fakes["apple"].jwks())
    return fakes


@pytest.fixture
async def make_user(
    app: FastAPI, settings: Settings
) -> Callable[..., Awaitable[tuple[User, dict[str, str]]]]:
    """동의를 마친 사용자와 Authorization 헤더를 만든다."""

    async def factory(
        *, status: UserStatus = UserStatus.ACTIVE, quality_log: bool = False, plan: str = "free"
    ) -> tuple[User, dict[str, str]]:
        async with app.state.sessionmaker() as session:
            user = User(status=status, plan=plan, ui_locale="ko")
            session.add(user)
            await session.flush()
            session.add(
                UserConsent(
                    user_id=user.id,
                    consent_type=ConsentType.QUALITY_LOG_COLLECTION,
                    version="2026-10-01",
                    agreed=quality_log,
                )
            )
            await session.commit()
        token = create_access_token(user.id, settings)
        return user, {"Authorization": f"Bearer {token}"}

    return factory
