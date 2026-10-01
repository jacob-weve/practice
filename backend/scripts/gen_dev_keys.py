"""로컬 개발용 JWT 서명 키와 데이터 암호화 키를 만들어 .env 형식으로 출력한다.

사용법: uv run python scripts/gen_dev_keys.py >> .env
운영 키는 Secrets Manager/KMS에서 관리하며 이 스크립트로 만들지 않는다.
"""

import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _env_value(pem: bytes) -> str:
    # pydantic-settings는 큰따옴표 안의 \n을 줄바꿈으로 해석한다.
    return '"' + pem.decode().strip().replace("\n", "\\n") + '"'


def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    print(f"JWT_PRIVATE_KEY={_env_value(private)}")
    print(f"JWT_PUBLIC_KEY={_env_value(public)}")
    print(f"DATA_ENCRYPTION_KEY={base64.b64encode(os.urandom(32)).decode()}")


if __name__ == "__main__":
    main()
