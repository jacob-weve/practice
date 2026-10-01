---
name: add-oauth-provider
description: Add or modify a social login provider (OAuth 2.0/OIDC) in the TalkSoft backend and web app, following the existing kakao/google/naver/apple pattern and security rules. Use when adding a new provider or changing provider-specific behavior.
---

# 소셜 로그인 제공자 추가

기존 4종(카카오·구글·네이버·애플)과 같은 구조로 만든다. 보안 규칙은 CLAUDE.md §3을 따른다.

## Backend

1. **enum**: `app/db/models/auth.py`의 `SocialProvider`에 값 추가 → PG enum이 바뀌므로 `db-migration` 스킬로 마이그레이션 작성
   (`ALTER TYPE social_provider ADD VALUE '...'`는 autogenerate가 만들지 않으니 직접 작성)
2. **provider 클래스**: `app/auth/providers/<name>.py`
   - `OAuthProvider` 상속, `name`, `authorize_endpoint`, `token_endpoint`, `scopes`, `client_id` 구현
   - `token_endpoint = "..."  # noqa: S105 (URL)`
   - `supports_pkce`: 제공자가 PKCE를 공식 지원할 때만 `True` (서버 측 PKCE 바인딩은 항상 동작)
   - `uses_nonce`: OIDC가 아니면 `False`
   - `authenticate()`:
     - 토큰 교환은 `self._post_token()` 사용 (재시도 금지, 5xx→`ProviderUnavailableError`, 4xx→`ProviderDeniedError`)
     - OIDC면 `verify_id_token()`로 서명→iss→aud→exp/iat→nonce 검증. 아니면 프로필 API 호출(멱등이므로 백오프 재시도 2회 허용)
     - 불리언 클레임은 `as_bool()`로 정규화
     - 탈퇴 시 revoke에 토큰이 필요할 때만 `ProviderIdentity.refresh_token`을 채운다(서비스가 AES-GCM으로 암호화 저장)
   - `revoke()`: 실패 시 `ProviderUnavailableError`를 던지면 서비스가 `oauth:revoke_queue`에 적재한다
3. **등록**: `app/auth/providers/__init__.py`의 `PROVIDERS`
4. **설정**: `core/config.py`에 `<name>_client_id`, `<name>_client_secret: SecretStr` 추가 → `backend/.env.example` 갱신
5. **테스트** (`tests/integration/test_auth_login.py` 패턴):
   - OIDC면 `tests/conftest.py`의 `idps` 픽스처에 `FakeIdP`와 JWKS 라우트 추가
   - 성공 로그인, 토큰 교환 실패(500/400), id_token 위조(nonce/aud/iss/만료), 이메일 미제공 가입
6. `uv run alembic check`와 `verify-changes` 스킬 실행

## Web

1. `web/lib/config.ts`의 `PROVIDERS`에 추가 (redirect URI 규칙 확인)
2. `components/SocialLoginButton.tsx`에 브랜드 스타일 추가 — 공식 브랜드 가이드라인 준수
3. `web/locales/*/auth.json`의 `continueWith.<name>` 문구 추가 (ko/en/ja 모두)

## 문서

- `docs/ARCHITECTURE.md §4.3` 제공자별 차이 표에 열 추가
- `docs/API_SPEC.md` `Provider` enum, 1.2 제공자별 서버 처리 표
- `docs/PRD.md` 제공자별 수집 항목 표
- 외부 콘솔 등록(Redirect URI, 동의 항목)은 `docs/PLAN.md`에 미완료 항목으로 추가
