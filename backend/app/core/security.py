import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings
from app.core.errors import TokenExpiredError, TokenInvalidError

ACCESS_TOKEN_ALGORITHM = "RS256"  # noqa: S105


def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
        "jti": uuid.uuid4().hex,
        "scope": "user",
    }
    return jwt.encode(
        claims,
        settings.jwt_private_key.get_secret_value(),
        algorithm=ACCESS_TOKEN_ALGORITHM,
        headers={"kid": settings.jwt_key_id},
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalidError(log_detail=type(exc).__name__) from exc
    return claims


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def generate_opaque(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def pkce_s256(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _aes_key(settings: Settings) -> bytes:
    key = base64.b64decode(settings.data_encryption_key.get_secret_value())
    if len(key) != 32:
        raise RuntimeError("DATA_ENCRYPTION_KEY must be 32 bytes (base64)")
    return key


def encrypt_secret(plaintext: str, settings: Settings) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_aes_key(settings)).encrypt(nonce, plaintext.encode(), None)


def decrypt_secret(ciphertext: bytes, settings: Settings) -> str:
    nonce, body = ciphertext[:12], ciphertext[12:]
    return AESGCM(_aes_key(settings)).decrypt(nonce, body, None).decode()
