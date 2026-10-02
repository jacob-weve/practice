# 말랑톡 (TalkSoft) — 구현 단계 체크리스트

> 목표: **1차 프로토타입** — 소셜 로그인 4종, 말투 변환 One-shot(SSE), 감정 온도계/독소 감지, 답장 해석기가 웹에서 끝까지 동작하는 상태
> 참조: [PRD.md](./PRD.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [DB_SCHEMA.md](./DB_SCHEMA.md) · [API_SPEC.md](./API_SPEC.md) · [CLAUDE.md](../CLAUDE.md)

---

## Step 1. 환경 세팅 및 문서 검토

### 1.1 문서 검토
- [ ] PRD의 P0 요구사항 목록을 확정하고 범위 외 항목에 합의
- [ ] ARCHITECTURE의 모델 티어링 기준과 라우팅 규칙 초기값 검토
- [x] DB_SCHEMA와 API_SPEC의 필드 이름·Enum이 서로 일치하는지 교차 검증 (인증 영역만 구현하며 확인, 나머지는 Step 3 착수 시)
- [ ] PRD §9 오픈 이슈 3건에 담당자와 결정 기한 지정

### 1.2 저장소 및 개발 환경
- [x] Git 저장소 초기화
- [ ] `main` 브랜치 보호 규칙 설정 (GitHub 저장소 관리자 권한 필요)
- [x] 모노레포 구조 생성 (`backend/`, `web/`, `mobile/`, `docs/`, `infra/`) — [CLAUDE.md §4](../CLAUDE.md) 참고
- [x] Python 3.12 + `uv` 프로젝트 생성, FastAPI·Uvicorn·Pydantic v2·SQLAlchemy 2.0·asyncpg·Alembic·httpx·PyJWT·redis 설치
- [x] Next.js 15 + TypeScript + Tailwind + next-intl 프로젝트 생성
- [x] `docker-compose.yml`: PostgreSQL 16, Redis 7, backend, web
- [x] `.env.example` 작성 (실제 비밀값 커밋 금지), `pydantic-settings` 기반 `core/config.py`
- [x] pre-commit: ruff, ruff-format, mypy, eslint, **gitleaks** (설치: `uvx pre-commit install`)
- [ ] prettier 설정 (Step 7에서 추가)
- [x] CI 파이프라인(GitHub Actions): lint → type check → test → pip-audit

### 1.3 외부 서비스 등록
- [ ] 카카오 개발자 앱 생성, OIDC 활성화, Redirect URI 등록, 동의 항목(닉네임, 이메일) 설정
- [ ] Google Cloud OAuth 클라이언트(웹/iOS/Android) 생성, 동의 화면 구성
- [ ] 네이버 개발자센터 애플리케이션 등록, 제공 정보(이메일, 별명) 선택
- [ ] Apple Developer: App ID, Services ID, Sign in with Apple Key(.p8) 발급, 도메인 검증, **Private Email Relay 발신 도메인 등록**
- [ ] LLM API 키 발급, 데이터 보존/학습 미사용 설정 확인
- [ ] 비밀값을 Secrets Manager(로컬은 `.env`)에 등록

---

## Step 2. OAuth 소셜 로그인 연동

### 2.1 DB 및 기반
- [x] Alembic 초기 마이그레이션 `0001`: Enum 타입, `users`, `social_accounts`, `refresh_tokens`, `user_consents` (SQLite 왕복 + PostgreSQL 오프라인 SQL로 검증)
- [ ] 실제 PostgreSQL에 `alembic upgrade head` 적용 확인 (Docker 기동 필요)
- [x] `core/security.py`: RS256 키 로딩(`kid`), Access Token 발급/검증, SHA-256 해시 유틸
- [x] `core/errors.py`: `AuthError` 계층과 에러 코드 → HTTP 매핑, i18n 메시지
- [x] 인증 의존성 `get_current_user` (만료 → `AUTH_TOKEN_EXPIRED`, `status=pending_consent` → `CONSENT_REQUIRED`)

### 2.2 공통 OAuth 흐름
- [x] `OAuthProvider` 프로토콜 정의 (`build_authorize_url`, `exchange_code`, `fetch_identity`, `revoke`)
- [x] `GET /auth/authorize/{provider}`: state/nonce 생성, `code_challenge` 바인딩, Redis 저장(TTL 10분)
- [x] `redirect_uri` 화이트리스트 검증
- [x] state 1회용 소비(`GETDEL`), 불일치/만료 시 `AUTH_INVALID_STATE`
- [x] JWKS 조회 및 Redis 캐시(TTL 1시간, `kid` 미스 시 강제 갱신)
- [x] id_token 공통 검증기: 서명, `iss`, `aud`, `exp`(시계 오차 60초), `iat`, `nonce`

### 2.3 제공자별 구현
- [x] **카카오**: 토큰 교환, id_token 검증, 이메일/닉네임 매핑 (탈퇴 unlink는 Admin Key 사용)
- [x] **구글**: 토큰 교환, id_token 검증, `email_verified` 처리
- [x] **네이버**: 토큰 교환, `/v1/nid/me` 호출, `resultcode` 검사
- [x] **애플**: ES256 `client_secret` JWT 생성(캐시, 만료 전 갱신)
- [x] 애플: `POST /auth/callback/apple` form_post 수신 → handoff 코드 발급
- [x] 애플: 최초 `user`(이름) 저장, `is_private_email` / `email_verified` 문자열 정규화
- [x] 애플: provider refresh_token **AES-GCM 암호화 저장**(탈퇴 revoke용)
- [x] 애플: 서버 간 알림 웹훅(`/auth/apple/notifications`) 서명 검증 및 이벤트 처리

### 2.4 가입/토큰/동의
- [x] `POST /auth/login/{provider}`: `(provider, provider_user_id)` 조회 → 없으면 가입(트랜잭션)
- [x] 이메일이 같아도 자동 병합하지 않음 (테스트로 보장)
- [x] Refresh Token 발급(256bit 랜덤), 해시 저장, `family_id` 부여
- [x] 웹: `HttpOnly; Secure; SameSite=Strict` 쿠키 / 모바일: 바디 반환 (`X-Client-Platform`)
- [x] `POST /auth/refresh`: Rotation, `SELECT ... FOR UPDATE`, **재사용 감지 시 family 전체 폐기**
- [x] `POST /auth/logout`, `POST /auth/consents`, `POST /auth/link/{provider}`
- [x] `DELETE /users/me`: 제공자 연결 해제(실패 시 Redis `oauth:revoke_queue` 적재) + CASCADE 삭제
- [ ] revoke 재시도 큐 소비 워커

### 2.5 프론트엔드 로그인
- [x] PKCE 유틸(`code_verifier` 생성, S256 challenge), verifier는 `sessionStorage`에 일시 보관 후 즉시 삭제
- [x] 로그인 화면: 제공자 4종 버튼(브랜드 색상 적용)
- [ ] 제공자 공식 로고 에셋 적용 및 브랜드 가이드 검수
- [x] 콜백 페이지(`/auth/callback/[provider]`) → `POST /auth/login/{provider}`
- [x] 약관 동의 모달(필수 3 + 선택 2), `pending_consent` 처리
- [x] Access Token 메모리 보관 + 401 시 single-flight refresh 인터셉터

### 2.6 테스트
- [x] 제공자 HTTP 응답 모킹(respx)으로 4종 로그인 성공/실패 단위 테스트
- [x] state 재사용, PKCE 불일치, nonce 불일치, 만료된 id_token, 잘못된 `aud` 거부 테스트
- [x] Refresh Rotation과 재사용 탐지 통합 테스트(동시 요청 포함)
- [x] 애플 Relay 이메일 및 이메일 미제공 가입 테스트
- [x] 로그에 토큰/이메일이 찍히지 않는지 검사하는 테스트

---

## Step 3. LLM 파이프라인 기반

- [x] 마이그레이션 `0002`: `tone_options`, `prompt_templates`, `transformation_logs`
- [x] 시드: 페르소나 6종 × (ko, en, ja), 프롬프트 템플릿 v1 (`tone_transform`, `tone_analyze`, `reply_interpret`, `guardrail_classify`) — `uv run python -m seeds.apply` (멱등)
- [x] `llm/client.py`: Provider 추상화, async 스트리밍 호출, 첫 이벤트 타임아웃 5초, 같은 티어 대체 모델, 서킷 브레이커(프로세스 단위)
- [x] `llm/router.py`: Light/Heavy 라우팅 규칙, 모델 ID는 환경변수
- [x] Redis 전역 동시성 제한(티어별, 초과 시 `LLM_BUSY` 503)
- [x] `llm/schemas.py`: One-shot 출력 Pydantic 모델(`intent → emotion → red_flags → variants` 순서)
- [x] 구조화 출력(`output_config.format`) 연동, 검증 실패 시 1회 재시도
- [x] 프롬프트 캐싱 표시(시스템 지침에 `cache_control`, 페르소나·옵션은 user 쪽)
- [ ] 캐시 적중 확인: v1 시스템 프롬프트는 모델의 최소 캐시 길이보다 짧을 수 있어 실제 API로 `cache_read_input_tokens`를 측정해야 함
- [x] 사용량(input/output/cached tokens), TTFT, 지연을 `CallResult`로 수집 (적재는 Step 5 로그 작성기)
- [ ] 실제 Anthropic API로 티어별 호출 확인 (API 키 필요)

---

## Step 4. Guardrail & 프라이버시 레이어

- [x] 입력 정규화: NFC, 제로폭/제어문자 제거, 길이 상한
- [x] 규칙 기반 인젝션 탐지(다국어 시그니처, 구분 태그 위조) → 위험 점수
- [x] 경량 모델 분류기(`safe / injection / jailbreak / harmful`) + 임계값 0.7 — 본 호출과 동시에 실행하고 통과 전까지 출력 보류
- [x] 프롬프트 조립기: `system`/`user` 분리, 데이터 블록 이스케이프
- [x] 카나리아 토큰으로 시스템 프롬프트 유출 탐지 (`LLM_CANARY_TOKEN`)
- [x] 출력 안전 필터(욕설 사전 기반 variant/추천 답장 제외)
- [ ] 조종성·혐오 표현 필터 고도화(현재는 욕설 단어 목록만)
- [x] `privacy/pii.py`: 정규식(전화, 이메일, 주민번호, 카드, 계좌, 주소) + 호칭 기반 인명 마스킹, 토큰 치환/복원
- [ ] 인명 NER 도입 검토(현재는 '씨/님/직함' 패턴만)
- [x] 구조화 로그 스크러빙(바디 미기록, 토큰·이메일·원문 키 마스킹)
- [ ] Sentry 연동 및 `before_send` 스크러빙
- [x] Rate Limit(Redis 고정 윈도우, 분·일 단위), `X-RateLimit-*` 헤더
- [x] **레드팀 테스트셋** 50건(인젝션 25·탈옥 10·유해 15) + 정상 30건. 규칙 레이어: 오탐 0건, 공격 탐지 ≥ 80%
- [ ] 실제 분류 모델로 차단율 ≥ 95%·오탐률 ≤ 2% 측정 (`TALKSOFT_LIVE_LLM=1 uv run pytest tests/redteam -m live`, API 키 필요)

---

## Step 5. 말투 변환 & 감정 분석 API

- [x] `GET /tone/options` (로케일별)
- [x] `POST /tone/transform` JSON 응답 구현
- [x] SSE 스트리밍: 증분 JSON 파서, `meta → analysis → red_flags → variant×3 → done` 이벤트
- [x] 클라이언트 연결 종료 감지 시 LLM 스트림 취소
- [x] keep-alive 주석(15초), `X-Accel-Buffering: no`
- [x] 출력 검증: 조각별·최종 스키마, red_flag 오프셋은 서버가 계산(UTF-16), 온도 범위
- [x] `POST /tone/analyze` (Light 티어)
- [x] Opt-in 시 마스킹 로그 적재, 미동의 시 메트릭만 적재 (스트림 종료 후 기록)
- [ ] 골든셋 30건(페르소나 × 관계 × 언어)으로 의도 보존율·자연스러움 수동 평가 (실제 API 필요)

---

## Step 6. 답장 심리 해석기 API

- [x] `POST /reply/interpret` 프롬프트 v1 (단정 금지, 확률·근거 제시, 조종성 답장 금지)
- [x] JSON 응답 및 SSE(`analysis → interpretation×N → guide → reply×3 → done`)
- [x] 대화 맥락 길이 제한(20턴, 턴당 500자, 총 3,000자) 및 화자 구분 데이터 블록화
- [x] `disclaimer` i18n 적용
- [x] 안전 장치 테스트: 가드레일이 모든 턴을 검사, 턴 태그 위조 차단, 부적절한 추천 답장 제외
- [ ] 실제 모델로 집착·감시·가스라이팅 유도 요청 거절 확인 (레드팀 HARMFUL 셋 활용)

---

## Step 7. 프론트엔드 핵심 화면

- [x] 레이아웃, 네비게이션, 테마(시스템 설정 따라 라이트/다크)
- [x] 상대 메시지 입력 + 스크린샷 업로드 → **온디바이스 OCR**(Tesseract.js, 처음 쓸 때만 로드) 프로토타입
- [ ] 실제 메신저 스크린샷으로 OCR 품질 확인(말풍선 화자 구분은 미지원)
- [x] 독소 하이라이트(`RedFlagPreview`, 오프셋 기반) + 표현별 대체 문구 '바꾸기'
- [x] `PersonaSelector`, `RelationSelector`, `LanguageSelector`
- [x] SSE 클라이언트(`lib/sse.ts`, `fetch` + `ReadableStream`), 이벤트별 점진 렌더링
- [x] `EmotionThermometer` (0–100°C 게이지, 결과 카드에 올리면 변환 후 온도 표시, 구간 색상)
- [x] `VariantCard` ×3 (복사/공유 → `POST /feedback`)
- [x] 답장 해석기 화면(해석 카드, 가이드, 추천 답장)
- [x] 히스토리(IndexedDB, 최대 500건, 고정 항목은 보존, 전체 삭제)
- [x] 설정(화면·결과 언어, 품질 로그 동의 토글, 연결 계정 표시, 로그아웃, 탈퇴)
- [ ] 설정에서 다른 소셜 계정 추가 연결 UI (API `/auth/link/{provider}`는 구현됨)
- [x] 에러 코드별 사용자 메시지(`ErrorNotice`)
- [ ] 실제 브라우저에서 전체 흐름 수동 점검 (OAuth 앱 등록 후)

---

## Step 8. 다국어 (i18n)

- [x] `locales/{ko,en,ja}/{common,auth,errors,nav,tone,interpret,history,settings}.json` 구성 (백엔드·웹 에러 카탈로그 동기화 테스트 포함)
- [x] 백엔드 `Accept-Language` 협상과 에러 메시지 번역 (SSE `error` 이벤트 포함)
- [x] UI 언어와 변환 출력 언어 분리 설정
- [x] 언어별 존댓말 매핑(`app/tone/formality.py`: ko 하십시오체/해요체/반말, ja 敬語/丁寧語/タメ口, en formal/neutral/casual, `auto`면 관계로 결정) 프롬프트 반영
- [ ] 교차 언어 변환 골든셋(en→ko, ko→ja 등) 10건 평가
- [ ] 하드코딩 문자열 검출 lint 규칙 적용

---

## Step 9. 품질·보안 점검

- [x] 테스트 커버리지 backend 95% (auth/service 93%, guardrails 97%, privacy 100%) — greenlet 추적 설정으로 정확히 측정
- [x] OWASP ASVS L1 자가 점검 → [SECURITY_CHECKLIST.md](./SECURITY_CHECKLIST.md) (남은 조치: 실모델 레드팀 측정, CSP, 인프라 TLS, 침투 테스트)
- [x] 의존성 취약점 스캔 0건(pip-audit, pnpm audit — next-intl 4.x 업그레이드, postcss override), 비밀값 스캔은 CI(gitleaks)
- [ ] gitleaks를 로컬에서 한 번 실행 (이 환경에 미설치)
- [ ] 부하 테스트(k6): 동시 SSE 200 연결, TTFT p95 ≤ 1.5초 확인 (실제 인프라·API 키 필요)
- [ ] 비용 측정: 요청당 평균 비용 ≤ $0.004, 티어 분포 확인 (`transformation_logs`의 토큰 수로 집계 가능, 실제 트래픽 필요)
- [x] 개인정보 처리방침 초안 → [PRIVACY_POLICY_DRAFT.md](./PRIVACY_POLICY_DRAFT.md) (구현 대조표 포함)
- [ ] 이용약관 초안, 법무 검토 요청

---

## Step 10. 1차 프로토타입 완성

- [x] 배포 산출물: `backend/Dockerfile`, `web/Dockerfile`(Next standalone), `infra/docker-compose.yml`(postgres·redis·backend·web), 주기 작업 `python -m app.jobs purge-logs|revoke-queue`
- [ ] Docker 이미지 실제 빌드·기동 확인 (이 환경은 Docker 데몬·compose 플러그인 없음. web standalone 서버는 로컬에서 기동 확인)
- [ ] staging 배포(환경변수/비밀값 주입)
- [ ] 4개 제공자 staging Redirect URI 등록 및 실기기 로그인 확인
- [ ] 대시보드: 지연(TTFT), 토큰 비용, Guardrail 차단율, 파싱 실패율, 로그인 성공률
- [ ] 알림 규칙 설정(파싱 실패 > 2%, TTFT p95 > 3초, 로그인 실패 > 5%)
- [ ] 내부 사용자 10명 대상 클로즈드 베타, 피드백 수집
- [ ] 회고: 라우팅 임계값, 프롬프트 v2, Guardrail 임계값 조정 항목 정리
- [ ] **완료 기준(DoD)**
  - [ ] 카카오/구글/네이버/애플 로그인 → 동의 → 변환 → 결과 복사가 웹에서 끝까지 동작
  - [ ] `/tone/transform` SSE로 감정·독소·변환 3종을 LLM 1회 호출로 받음
  - [ ] 대화 원문이 DB·로그 어디에도 남지 않음을 검증
  - [ ] Refresh 재사용 탐지 시나리오 통과
  - [ ] 레드팀 테스트셋 차단율 ≥ 95%
