"""테스트용 가짜 OAuth 제공자(IdP)와 키 생성 도우미."""

import asyncio
import base64
import json
import os
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.security import pkce_s256
from app.llm.client import (
    LlmCall,
    Started,
    StreamDone,
    StreamEvent,
    TextDelta,
    TransientProviderError,
)


def rsa_pem_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


def ec_private_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def aes_key_b64() -> str:
    return base64.b64encode(os.urandom(32)).decode()


class FakeIdP:
    """RSA 키로 id_token에 서명하고 같은 키를 JWKS로 노출하는 가짜 제공자."""

    def __init__(self, issuer: str, audience: str, kid: str = "k1") -> None:
        self.issuer = issuer
        self.audience = audience
        self.kid = kid
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update(kid=self.kid, alg="RS256", use="sig")
        return {"keys": [jwk]}

    def id_token(self, sub: str, nonce: str | None, /, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": sub,
            "iat": now,
            "exp": now + 600,
        }
        if nonce is not None:
            claims["nonce"] = nonce
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self.kid})


def new_verifier() -> str:
    return secrets.token_urlsafe(48)


async def start_authorization(
    client: httpx.AsyncClient, provider: str, redirect_uri: str, verifier: str
) -> tuple[str, str | None]:
    """인가 URL을 받아 (state, nonce)를 돌려준다."""
    res = await client.get(
        f"/api/v1/auth/authorize/{provider}",
        params={
            "code_challenge": pkce_s256(verifier),
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
        },
    )
    assert res.status_code == 200, res.text
    query = parse_qs(urlparse(res.json()["authorize_url"]).query)
    nonce = query.get("nonce", [None])[0]
    return res.json()["state"], nonce


# ---------------------------------------------------------------- LLM fakes


@dataclass
class Script:
    """가짜 제공자가 한 번의 호출에서 할 일."""

    text: str = "{}"
    stop_reason: str = "end_turn"
    fail: str | None = None  # "before_start" | "hang" | "mid_stream"
    chunk: int = 7


@dataclass
class RecordedCall:
    model: str
    call: LlmCall
    effort: str | None
    server_fallback: bool


@dataclass
class FakeLlmProvider:
    """모델별 스크립트를 순서대로 소비한다. 스크립트가 없으면 default_text로 성공한다."""

    scripts: dict[str, list[Script]] = field(default_factory=dict)
    by_template: dict[str, str] = field(default_factory=dict)  # 시스템 프롬프트 키워드 → 응답
    calls: list[RecordedCall] = field(default_factory=list)

    def queue(self, model: str, *scripts: Script) -> None:
        self.scripts.setdefault(model, []).extend(scripts)

    async def stream(
        self, model: str, call: LlmCall, *, effort: str | None, server_fallback: bool
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append(RecordedCall(model, call, effort, server_fallback))
        queue = self.scripts.get(model) or []
        script = queue.pop(0) if queue else Script(text=self._default(call))
        if script.fail == "before_start":
            raise TransientProviderError("status:529")
        if script.fail == "hang":
            await asyncio.sleep(3600)
        yield Started(model)
        for i in range(0, len(script.text), script.chunk):
            if script.fail == "mid_stream" and i > 0:
                raise TransientProviderError("status:500")
            yield TextDelta(script.text[i : i + script.chunk])
        yield StreamDone(model, script.stop_reason, 100, 50, 80)

    def _default(self, call: LlmCall) -> str:
        for keyword, text in self.by_template.items():
            if keyword in call.system:
                return text
        return "{}"
