from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    default_locale: str = "ko"
    supported_locales: list[str] = ["ko", "en", "ja"]

    database_url: str = "postgresql+asyncpg://talksoft:talksoft@localhost:5432/talksoft"
    redis_url: str = "redis://localhost:6379/0"

    web_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]
    # OAuth redirect_uri 화이트리스트. 인가 요청과 로그인 요청 모두 이 목록으로 검증한다.
    oauth_redirect_uris: list[str] = Field(default_factory=list)

    # 서비스 JWT (RS256). PEM 원문을 환경변수/Secrets Manager로 주입한다.
    jwt_private_key: SecretStr = SecretStr("")
    jwt_public_key: str = ""
    jwt_key_id: str = "local-1"
    jwt_issuer: str = "https://api.talksoft.app"
    jwt_audience: str = "talksoft-app"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 14 * 24 * 3600
    refresh_reuse_grace_seconds: int = 5
    refresh_cookie_name: str = "ts_rt"
    refresh_cookie_path: str = "/api/v1/auth"
    cookie_secure: bool = True

    # 제공자 토큰 암호화용 AES-256-GCM 키 (base64, 32바이트). 운영에서는 KMS에서 주입한다.
    data_encryption_key: SecretStr = SecretStr("")

    oauth_state_ttl_seconds: int = 600
    oauth_http_timeout_seconds: float = 5.0
    jwks_cache_ttl_seconds: int = 3600

    kakao_client_id: str = ""
    kakao_client_secret: SecretStr = SecretStr("")
    kakao_admin_key: SecretStr = SecretStr("")  # 탈퇴 시 unlink용
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    naver_client_id: str = ""
    naver_client_secret: SecretStr = SecretStr("")
    apple_client_id: str = ""  # Services ID (web)
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: SecretStr = SecretStr("")  # .p8 PEM 원문

    consent_version: str = "2026-10-01"

    # LLM. 모델 ID는 코드에 하드코딩하지 않는다 (CLAUDE.md §2.1).
    anthropic_api_key: SecretStr = SecretStr("")  # 비어 있으면 SDK 기본 자격 증명 탐색
    llm_model_light: str = "claude-haiku-4-5"
    llm_model_heavy: str = "claude-sonnet-5-5"
    # 제공사 장애(5xx/타임아웃) 시 같은 티어에서 쓸 보조 모델
    llm_model_light_fallback: str = "claude-sonnet-5-5"
    llm_model_heavy_fallback: str = "claude-opus-5-5"
    # 모델별 effort. 목록에 없는 모델(Haiku 4.5)에는 effort를 보내지 않는다(400).
    llm_model_effort: dict[str, str] = {"claude-sonnet-5-5": "low", "claude-opus-5-5": "low"}
    # 안전 분류기 거절 시 서버 측 대체 모델 재시도(fallbacks="default")를 켤 모델
    llm_server_fallback_models: list[str] = ["claude-sonnet-5-5", "claude-opus-5-5"]
    llm_first_event_timeout_seconds: float = 5.0
    llm_request_timeout_seconds: float = 30.0
    llm_max_concurrency: dict[str, int] = {"light": 50, "heavy": 20}
    llm_circuit_failure_threshold: int = 3
    llm_circuit_open_seconds: float = 30.0
    # 시스템 프롬프트 유출 탐지용. 배포마다 바꾸고 비밀로 관리한다.
    llm_canary_token: SecretStr = SecretStr("")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
