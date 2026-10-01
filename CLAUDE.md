# CLAUDE.md — 말랑톡 (TalkSoft) 프로젝트 컨벤션

이 파일은 AI 코딩 어시스턴트와 개발자가 이 저장소에서 작업할 때 지켜야 할 규칙을 정리한다.
설계 근거는 `docs/`의 문서를 따른다: [PRD.md](docs/PRD.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [DB_SCHEMA.md](docs/DB_SCHEMA.md), [API_SPEC.md](docs/API_SPEC.md), [PLAN.md](docs/PLAN.md).

---

## 1. 프로젝트 요약

- **서비스**: AI 기반 맞춤형 말투 변환 및 감정 분석 메시지 코칭
- **Backend**: Python 3.12, FastAPI(async), SQLAlchemy 2.0 async, PostgreSQL 16, Redis 7
- **Frontend**: Next.js 15(App Router) + TypeScript, React Native(Expo)
- **핵심 원칙**: 대화 원문 비저장(Stateless) · LLM One-shot JSON 호출 · 다층 Guardrail · 모델 티어링

### 자주 쓰는 명령
```bash
# backend
cd backend && uv sync
uv run uvicorn app.main:app --reload
uv run pytest -q
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "<message>"

# web
cd web && pnpm install && pnpm dev
pnpm lint && pnpm typecheck && pnpm test

# 전체 로컬 환경
docker compose -f infra/docker-compose.yml up -d
```

### 개발 환경 메모
- `uv`는 `~/.local/bin`, `pnpm`은 `~/.npm-global/bin`에 있다. 셸에서 못 찾으면 `export PATH=~/.local/bin:~/.npm-global/bin:$PATH`.
- 저장소 루트의 `.venv`(Python 3.9)가 활성화돼 있으면 uv가 경고한다. backend 명령 전에 `unset VIRTUAL_ENV`.
- 테스트는 PostgreSQL/Redis 없이 SQLite(aiosqlite) + fakeredis로 돌아간다. 외부 HTTP(OAuth 제공자, LLM)는 respx로 모킹하고, 실제 네트워크 호출 테스트는 만들지 않는다.
- SQLite에서 통과해도 PostgreSQL 전용 동작(enum 타입, `text[]`, 부분 인덱스, `FOR UPDATE`)은 다르다. 마이그레이션은 `.claude/skills/db-migration` 절차로 PostgreSQL SQL까지 확인한다.
- 반복 작업 절차는 `.claude/skills/`에 있다: `verify-changes`(검사 실행), `db-migration`(마이그레이션 생성·검증), `add-oauth-provider`(제공자 추가).

---

## 2. 코드 작성 스타일

### 2.1 Python (backend)
- 포맷/린트: `ruff format`, `ruff check`(규칙셋 `E,F,I,B,UP,S,ASYNC`), 타입 검사 `mypy --strict`
- 줄 길이 100. 문자열은 큰따옴표.
- **모든 I/O는 async.** `requests`, 동기 DB 드라이버, `time.sleep` 금지. 외부 HTTP는 공용 `httpx.AsyncClient`(앱 lifespan에서 생성)를 사용한다.
- CPU 무거운 작업(대량 정규식, OCR)은 `anyio.to_thread.run_sync`로 오프로드한다.
- 요청/응답 모델은 Pydantic v2로 정의하고 `model_config = ConfigDict(extra="forbid")`를 기본으로 한다.
- 라우터는 얇게: `router.py`(HTTP) → `service.py`(비즈니스 로직) → `repository`/DB. 라우터에서 직접 SQL 금지.
- 의존성 주입은 FastAPI `Depends`를 사용한다. 전역 가변 상태 금지.
- 설정값은 `app/core/config.py`의 `Settings`로만 읽는다. 코드에서 `os.environ` 직접 접근 금지.
- **LLM 모델 ID, 임계값, 프롬프트를 코드에 하드코딩하지 않는다.** 모델은 `settings.LLM_MODEL_LIGHT/HEAVY`, 프롬프트는 `prompt_templates` 테이블에서 읽는다.
- 이름: 모듈/함수 `snake_case`, 클래스 `PascalCase`, 상수 `UPPER_SNAKE`. 불리언은 `is_`/`has_` 접두사.
- 주석은 "왜"를 쓴다. 자명한 코드에 주석을 달지 않는다.

### 2.2 TypeScript (web/mobile)
- `strict: true`, `any` 금지(불가피하면 `unknown` + 타입 가드).
- ESLint + Prettier. 컴포넌트는 함수형 + `PascalCase.tsx`, 훅은 `useXxx.ts`.
- API 타입은 백엔드 OpenAPI에서 생성한다(`pnpm gen:api`). 손으로 중복 정의하지 않는다.
- **UI 문자열 하드코딩 금지** — 반드시 i18n 키(`t("tone.persona.polite")`)를 사용한다.
- 서버 상태는 TanStack Query, 스트리밍은 `lib/sse.ts`의 공용 파서만 사용한다.

### 2.3 API 규칙
- 경로는 `/api/v1/` 접두사, 복수형 명사, kebab-case.
- JSON 필드는 `snake_case`.
- 에러는 항상 `{"error": {"code", "message", "request_id", "details"}}` 형식. 새 에러 코드를 추가하면 `docs/API_SPEC.md §0.3`, `backend/app/locales/*/errors.json`, `web/locales/*/errors.json`을 함께 갱신한다.
- API 스펙이 바뀌면 같은 PR에서 `docs/API_SPEC.md`를 갱신한다.

### 2.4 커밋/PR
- Conventional Commits: `feat(auth): add apple form_post callback`
- PR 하나에 하나의 관심사. 마이그레이션은 별도 커밋.
- 보안/프라이버시에 영향을 주는 변경은 PR 설명에 `Security/Privacy Impact` 섹션을 쓴다.

---

## 3. OAuth 인증 예외 처리 규칙

### 3.1 예외 계층
```python
class AppError(Exception):
    code: str; http_status: int

class AuthError(AppError): ...
class InvalidStateError(AuthError):        code = "AUTH_INVALID_STATE";        http_status = 400
class PKCEMismatchError(AuthError):        code = "AUTH_PKCE_MISMATCH";        http_status = 400
class ProviderDeniedError(AuthError):      code = "AUTH_PROVIDER_DENIED";      http_status = 401
class IdTokenInvalidError(AuthError):      code = "AUTH_ID_TOKEN_INVALID";     http_status = 401
class TokenExpiredError(AuthError):        code = "AUTH_TOKEN_EXPIRED";        http_status = 401
class RefreshInvalidError(AuthError):      code = "AUTH_REFRESH_INVALID";      http_status = 401
class RefreshReusedError(AuthError):       code = "AUTH_REFRESH_REUSED";       http_status = 401
class ProviderUnavailableError(AuthError): code = "AUTH_PROVIDER_UNAVAILABLE"; http_status = 503
```
- 모든 도메인 예외는 `app/core/errors.py`에 정의하고, 전역 exception handler 하나에서 HTTP 응답으로 바꾼다.
- 제공자 SDK/httpx 예외를 라우터 밖으로 그대로 내보내지 않는다. 반드시 위 계층으로 감싼다.

### 3.2 규칙
1. **사용자에게는 일반화된 메시지만** 보낸다. 제공자 원본 에러 바디, 스택 트레이스, 검증 실패의 세부 사유(어떤 클레임이 틀렸는지)는 응답에 넣지 않는다. 상세 사유는 서버 로그에 `code`와 함께 남긴다(토큰 값 제외).
2. **state는 1회용**: 검증 성공/실패와 관계없이 Redis에서 즉시 삭제(`GETDEL`)한다.
3. **id_token 검증 순서**: 서명(JWKS, `kid`) → `iss` → `aud` → `exp`/`iat`(허용 오차 60초) → `nonce`. 하나라도 실패하면 `IdTokenInvalidError`.
4. **JWKS `kid` 미스**: 캐시를 1회 강제 갱신한 뒤 다시 검증한다. 그래도 없으면 실패. 갱신은 분당 1회로 제한한다.
5. **제공자 장애(5xx/타임아웃)**: 토큰 교환은 재시도하지 않는다(인가 코드는 1회용). `ProviderUnavailableError`로 응답한다. 프로필 조회(네이버 `/nid/me`)는 지수 백오프로 최대 2회 재시도할 수 있다.
6. **사용자 동의 취소**(`error=access_denied`): 에러로 기록하지 않고 `ProviderDeniedError`로 응답하며, 메트릭만 증가시킨다.
7. **애플 특이사항**:
   - `email_verified`, `is_private_email`은 `"true"`/`true` 둘 다 올 수 있으므로 반드시 정규화 헬퍼를 쓴다.
   - 최초 `user` 이름 저장은 가입 트랜잭션 안에서 처리한다. 실패하면 가입 전체를 롤백한다.
   - 이메일이 없어도 가입은 성공해야 한다.
8. **계정 병합 금지**: 이메일이 같다는 이유로 다른 제공자 계정을 자동 연결하지 않는다. 연결은 로그인한 사용자의 명시적 `/auth/link/{provider}` 요청으로만 한다.
9. **Refresh 재사용 탐지**: `RefreshReusedError`가 나면 같은 `family_id` 전체를 폐기하고 보안 이벤트 로그(`security.refresh_reuse`, user_id, family_id만)를 남긴다.
10. **동시 Refresh**: 행 잠금(`FOR UPDATE`)으로 처리한다. 경합에서 진 요청을 재사용으로 오판하지 않도록, 직전 회전 후 5초 이내 같은 부모 토큰 요청은 방금 발급한 자식 토큰 기준으로 처리한다(grace window).
11. 탈퇴 시 제공자 revoke가 실패해도 **사용자 데이터 삭제는 진행**하고, revoke는 재시도 큐로 넘긴다.

---

## 4. PII 및 토큰 보안 지침

### 4.1 절대 금지 (리뷰에서 반드시 반려)
- ❌ 사용자 대화 원문(context, draft, message, conversation)을 DB, 파일, 로그, 메트릭 레이블, 에러 리포트에 저장
- ❌ Access Token, Refresh Token, 제공자 토큰, `code`, `code_verifier`, `id_token`, `client_secret`을 로그에 출력(부분 출력 포함)
- ❌ Refresh Token 원문 DB 저장 (SHA-256 해시만)
- ❌ 제공자 refresh_token을 평문으로 저장 (AES-256-GCM + KMS 키)
- ❌ 비밀값을 코드, 테스트 픽스처, `.env.example`에 커밋
- ❌ 웹에서 토큰을 `localStorage`/`sessionStorage`에 저장 (Access는 메모리, Refresh는 HttpOnly 쿠키)
- ❌ 사용자 입력을 시스템 프롬프트에 문자열 연결로 삽입

### 4.2 필수
- ✅ 로그는 구조화(JSON) 로그로 남기고, `app/core/logging.py`의 PII 스크러버를 거친다. 키 이름 기반(`token`, `authorization`, `cookie`, `email`, `draft`, `context`, `message`) 마스킹은 기본이다.
- ✅ `transformation_logs`에 쓰기 전에는 반드시 `privacy.pii.mask()`를 호출하고, 사용자의 `quality_log_collection` 동의를 확인한다. 이 두 검사는 `TransformationLogWriter` 한 곳에서만 수행한다(우회 경로 금지).
- ✅ 로그에 사용자를 남길 때는 `user_id`(UUID)만 사용한다. 이메일·닉네임 금지.
- ✅ 이메일을 로그로 꼭 남겨야 하면 `sha256(email)[:12]`.
- ✅ 비교 연산에는 `hmac.compare_digest`(상수 시간 비교)를 쓴다.
- ✅ JWT 검증 시 `algorithms`를 명시한다(`["RS256"]`). `none` 알고리즘 허용 금지.
- ✅ 쿠키: `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`.
- ✅ CORS는 허용 오리진을 명시한다. `*`와 `allow_credentials=True`를 같이 쓰지 않는다.

### 4.3 LLM 프롬프트 보안
- 프롬프트는 `app/llm/prompts.py`의 `build_messages()`로만 조립한다. 사용자 입력은 `escape_user_block()`을 거친 뒤 `<draft>`, `<context>` 데이터 블록 안에만 넣는다.
- 모든 LLM 호출 전에 `guardrails.check()`를 통과해야 한다. 새 LLM 엔드포인트를 추가할 때 이 단계를 빼면 안 된다.
- LLM 출력은 항상 Pydantic 스키마로 검증한 뒤 클라이언트로 보낸다. 자유 텍스트를 그대로 반환하는 경로를 만들지 않는다.
- Guardrail 차단 로그에는 원문 대신 `risk_type`, `score`, `input_sha256`만 남긴다.

### 4.4 테스트에서
- 테스트 데이터에 실제 개인정보를 쓰지 않는다. 전화번호는 `010-0000-0000` 형식의 가짜 값을 쓴다.
- 로그 캡처 테스트(`caplog`)로 토큰·이메일·원문이 출력되지 않음을 검증하는 테스트를 auth/tone/reply 모듈마다 하나 이상 둔다.

---

## 5. 프로젝트 디렉터리 구조

```
talksoft/
├── CLAUDE.md
├── .claude/skills/                # 반복 작업 절차 (SKILL.md)
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── DB_SCHEMA.md
│   ├── API_SPEC.md
│   └── PLAN.md
├── backend/
│   ├── pyproject.toml             # ruff/mypy/pytest 설정 포함
│   ├── alembic/
│   │   └── versions/              # 0001_auth_tables.py, ...
│   ├── scripts/
│   │   └── gen_dev_keys.py        # 로컬 JWT/AES 키 생성
│   ├── app/
│   │   ├── main.py                # create_app(), lifespan(httpx/redis/db), 미들웨어
│   │   ├── locales/{ko,en,ja}/errors.json   # 에러 메시지 카탈로그
│   │   ├── core/
│   │   │   ├── config.py          # Settings (pydantic-settings)
│   │   │   ├── deps.py            # DbDep, RedisDep, HttpClientDep, SettingsDep
│   │   │   ├── security.py        # JWT, 해시, PKCE S256, AES-GCM
│   │   │   ├── errors.py          # AppError 계층, exception handler
│   │   │   ├── i18n.py
│   │   │   ├── logging.py         # 구조화 로그 + PII 스크러버
│   │   │   ├── middleware.py      # X-Request-ID
│   │   │   └── rate_limit.py
│   │   ├── auth/
│   │   │   ├── router.py
│   │   │   ├── service.py
│   │   │   ├── schemas.py
│   │   │   ├── deps.py            # CurrentUser, ActiveUser, AuthServiceDep
│   │   │   ├── state_store.py     # OAuth state / Apple handoff (Redis, 1회용)
│   │   │   ├── tokens.py          # refresh rotation / reuse detection
│   │   │   └── providers/
│   │   │       ├── base.py
│   │   │       ├── oidc.py        # 공통 id_token 검증, JWKS 캐시
│   │   │       ├── kakao.py
│   │   │       ├── google.py
│   │   │       ├── naver.py
│   │   │       └── apple.py
│   │   ├── users/router.py        # /users/me
│   │   ├── tone/                  # Step 5
│   │   ├── reply/                 # Step 6
│   │   ├── llm/                   # Step 3
│   │   │   ├── client.py          # provider 추상화, fallback, circuit breaker
│   │   │   ├── router.py          # light/heavy 라우팅
│   │   │   ├── guardrails.py
│   │   │   ├── prompts.py         # build_messages, escape_user_block
│   │   │   ├── schemas.py         # One-shot 출력 스키마
│   │   │   └── streaming.py       # 증분 JSON 파서, SSE 직렬화
│   │   ├── privacy/               # Step 4
│   │   │   ├── pii.py
│   │   │   └── log_writer.py      # TransformationLogWriter (유일한 로그 적재 경로)
│   │   └── db/
│   │       ├── base.py            # Base, uuid7, TextArray
│   │       ├── session.py
│   │       └── models/
│   └── tests/
│       ├── conftest.py            # SQLite + fakeredis + respx 픽스처
│       ├── fakes.py               # FakeIdP(JWKS 서명), PKCE 도우미
│       ├── unit/
│       ├── integration/
│       ├── redteam/               # 인젝션/탈옥 테스트셋 (Step 4)
│       └── golden/                # 변환 품질 골든셋 (Step 5)
├── web/
│   ├── app/                       # URL에 로케일 없음 (OAuth Redirect URI 고정)
│   │   ├── login/
│   │   ├── auth/callback/[provider]/
│   │   ├── transform/             # Step 7
│   │   ├── interpret/
│   │   ├── history/
│   │   └── settings/
│   ├── components/
│   ├── i18n/request.ts            # 쿠키 → Accept-Language → ko
│   ├── lib/
│   │   ├── api/client.ts          # apiFetch, single-flight refresh
│   │   ├── auth/                  # PKCE, 토큰 메모리 저장, 로그인 흐름
│   │   ├── sse.ts                 # Step 5
│   │   └── history-db.ts          # IndexedDB (Step 7)
│   ├── locales/{ko,en,ja}/{common,auth,errors}.json
│   └── tests/                     # vitest
├── mobile/
├── infra/
│   ├── docker-compose.yml
│   └── nginx/
└── .github/workflows/ci.yml
```

### 배치 규칙
- 도메인(auth, tone, reply, users)별로 `router.py / service.py / schemas.py`를 둔다.
- 도메인 간 직접 import는 `service` 레벨에서만 허용한다. 다른 도메인의 `router`를 import하지 않는다.
- LLM 호출은 반드시 `app/llm/`을 거친다. 도메인 코드에서 LLM SDK를 직접 import하지 않는다.
- 새 테이블은 `app/db/models/`에 모델을 추가하고 Alembic 마이그레이션과 `docs/DB_SCHEMA.md`를 함께 갱신한다.
- PostgreSQL 전용 타입은 테스트용 SQLite와 호환되게 쓴다: 배열은 `TextArray`, 부분 인덱스는 `postgresql_where`/`sqlite_where`에 `text(...)`.

---

## 6. 작업 시 체크리스트 (AI 어시스턴트용)

변경을 마치기 전에 확인한다:
- [ ] 관련 테스트를 추가/수정했고 `pytest`/`pnpm test`가 통과한다
- [ ] 새 로그 구문에 토큰·이메일·대화 원문이 들어가지 않는다
- [ ] 새 LLM 경로가 Guardrail → 프롬프트 격리 → 스키마 검증을 모두 거친다
- [ ] 새 사용자 노출 문자열이 i18n 키로 되어 있다
- [ ] API/DB가 바뀌었다면 `docs/API_SPEC.md`/`docs/DB_SCHEMA.md`를 갱신했다
- [ ] 완료한 항목을 `docs/PLAN.md`에 체크했다 (사람의 결정이 필요한 항목은 체크하지 않는다)
- [ ] 비밀값을 커밋하지 않았다
