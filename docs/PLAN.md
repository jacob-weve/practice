# 말랑톡 (TalkSoft) — 구현 단계 체크리스트

> 목표: **1차 프로토타입** — 소셜 로그인 4종, 말투 변환 One-shot(SSE), 감정 온도계/독소 감지, 답장 해석기가 웹에서 끝까지 동작하는 상태
> 참조: [PRD.md](./PRD.md) · [ARCHITECTURE.md](./ARCHITECTURE.md) · [DB_SCHEMA.md](./DB_SCHEMA.md) · [API_SPEC.md](./API_SPEC.md) · [CLAUDE.md](./CLAUDE.md)

---

## Step 1. 환경 세팅 및 문서 검토

### 1.1 문서 검토
- [ ] PRD의 P0 요구사항 목록을 확정하고 범위 외 항목에 합의
- [ ] ARCHITECTURE의 모델 티어링 기준과 라우팅 규칙 초기값 검토
- [ ] DB_SCHEMA와 API_SPEC의 필드 이름·Enum이 서로 일치하는지 교차 검증
- [ ] PRD §9 오픈 이슈 3건에 담당자와 결정 기한 지정

### 1.2 저장소 및 개발 환경
- [ ] Git 저장소 초기화, `main` 브랜치 보호 규칙 설정
- [ ] 모노레포 구조 생성 (`backend/`, `web/`, `mobile/`, `docs/`, `infra/`) — [CLAUDE.md §4](./CLAUDE.md) 참고
- [ ] Python 3.12 + `uv` 프로젝트 생성, FastAPI·Uvicorn·Pydantic v2·SQLAlchemy 2.0·asyncpg·Alembic·httpx·PyJWT·redis 설치
- [ ] Next.js 15 + TypeScript + Tailwind + next-intl 프로젝트 생성
- [ ] `docker-compose.yml`: PostgreSQL 16, Redis 7, backend, web
- [ ] `.env.example` 작성 (실제 비밀값 커밋 금지), `pydantic-settings` 기반 `core/config.py`
- [ ] pre-commit: ruff, ruff-format, mypy, eslint, prettier, **gitleaks**
- [ ] CI 파이프라인(GitHub Actions): lint → type check → test → pip-audit

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
- [ ] Alembic 초기 마이그레이션: Enum 타입, `users`, `social_accounts`, `refresh_tokens`, `user_consents`
- [ ] `core/security.py`: RS256 키 로딩(`kid`), Access Token 발급/검증, SHA-256 해시 유틸
- [ ] `core/errors.py`: `AuthError` 계층과 에러 코드 → HTTP 매핑, i18n 메시지
- [ ] 인증 의존성 `get_current_user` (만료 → `AUTH_TOKEN_EXPIRED`, `status=pending_consent` → `CONSENT_REQUIRED`)

### 2.2 공통 OAuth 흐름
- [ ] `OAuthProvider` 프로토콜 정의 (`build_authorize_url`, `exchange_code`, `fetch_identity`, `revoke`)
- [ ] `GET /auth/authorize/{provider}`: state/nonce 생성, `code_challenge` 바인딩, Redis 저장(TTL 10분)
- [ ] `redirect_uri` 화이트리스트 검증
- [ ] state 1회용 소비(`GETDEL`), 불일치/만료 시 `AUTH_INVALID_STATE`
- [ ] JWKS 조회 및 Redis 캐시(TTL 1시간, `kid` 미스 시 강제 갱신)
- [ ] id_token 공통 검증기: 서명, `iss`, `aud`, `exp`(시계 오차 60초), `iat`, `nonce`

### 2.3 제공자별 구현
- [ ] **카카오**: 토큰 교환, id_token 검증, 이메일/닉네임 매핑
- [ ] **구글**: 토큰 교환, id_token 검증, `email_verified` 처리
- [ ] **네이버**: 토큰 교환, `/v1/nid/me` 호출, `resultcode` 검사
- [ ] **애플**: ES256 `client_secret` JWT 생성(캐시, 만료 전 갱신)
- [ ] 애플: `POST /auth/callback/apple` form_post 수신 → handoff 코드 발급
- [ ] 애플: 최초 `user`(이름) 저장, `is_private_email` / `email_verified` 문자열 정규화
- [ ] 애플: provider refresh_token **AES-GCM 암호화 저장**(탈퇴 revoke용)
- [ ] 애플: 서버 간 알림 웹훅(`/auth/apple/notifications`) 서명 검증 및 이벤트 처리

### 2.4 가입/토큰/동의
- [ ] `POST /auth/login/{provider}`: `(provider, provider_user_id)` 조회 → 없으면 가입(트랜잭션)
- [ ] 이메일이 같아도 자동 병합하지 않음 (테스트로 보장)
- [ ] Refresh Token 발급(256bit 랜덤), 해시 저장, `family_id` 부여
- [ ] 웹: `HttpOnly; Secure; SameSite=Strict` 쿠키 / 모바일: 바디 반환 (`X-Client-Platform`)
- [ ] `POST /auth/refresh`: Rotation, `SELECT ... FOR UPDATE`, **재사용 감지 시 family 전체 폐기**
- [ ] `POST /auth/logout`, `POST /auth/consents`, `POST /auth/link/{provider}`
- [ ] `DELETE /users/me`: 제공자 연결 해제(재시도 큐) + CASCADE 삭제

### 2.5 프론트엔드 로그인
- [ ] PKCE 유틸(`code_verifier` 생성, S256 challenge), verifier는 `sessionStorage`에 일시 보관 후 즉시 삭제
- [ ] 로그인 화면: 제공자 4종 버튼(각 브랜드 가이드라인 준수)
- [ ] 콜백 페이지(`/auth/callback/[provider]`) → `POST /auth/login/{provider}`
- [ ] 약관 동의 모달(필수 3 + 선택 2), `pending_consent` 처리
- [ ] Access Token 메모리 보관 + 401 시 single-flight refresh 인터셉터

### 2.6 테스트
- [ ] 제공자 HTTP 응답 모킹(respx)으로 4종 로그인 성공/실패 단위 테스트
- [ ] state 재사용, PKCE 불일치, nonce 불일치, 만료된 id_token, 잘못된 `aud` 거부 테스트
- [ ] Refresh Rotation과 재사용 탐지 통합 테스트(동시 요청 포함)
- [ ] 애플 Relay 이메일 및 이메일 미제공 가입 테스트
- [ ] 로그에 토큰/이메일이 찍히지 않는지 검사하는 테스트

---

## Step 3. LLM 파이프라인 기반

- [ ] 마이그레이션: `tone_options`, `prompt_templates`, `transformation_logs`
- [ ] 시드: 페르소나 6종 × (ko, en, ja), 프롬프트 템플릿 v1 (`tone_transform`, `tone_analyze`, `reply_interpret`, `guardrail_classify`)
- [ ] `llm/client.py`: Provider 추상화, async 스트리밍 호출, 타임아웃(TTFT 5초), Fallback, 서킷 브레이커
- [ ] `llm/router.py`: Light/Heavy 라우팅 규칙, 모델 ID는 환경변수
- [ ] Redis 전역 동시성 세마포어(티어별)
- [ ] `llm/schemas.py`: One-shot 출력 Pydantic 모델(`intent → emotion → red_flags → variants` 순서)
- [ ] 구조화 출력(JSON Schema 강제) 연동, 파싱 실패 시 1회 재시도
- [ ] 프롬프트 캐싱 적용(시스템 지침 + 페르소나 정의 고정 prefix)
- [ ] 사용량(input/output/cached tokens), TTFT, 지연 메트릭 수집

---

## Step 4. Guardrail & 프라이버시 레이어

- [ ] 입력 정규화: NFC, 제로폭/제어문자 제거, 길이 상한
- [ ] 규칙 기반 인젝션 탐지(다국어 시그니처, 구분 태그 위조) → 위험 점수
- [ ] 경량 모델 분류기(`safe / injection / jailbreak / harmful`) + 임계값 설정
- [ ] 프롬프트 조립기: `system`/`user` 분리, 데이터 블록 이스케이프
- [ ] 카나리아 토큰으로 시스템 프롬프트 유출 탐지
- [ ] 출력 안전 필터(욕설·혐오·조종성 표현 variant 제외)
- [ ] `privacy/pii.py`: 정규식(전화, 이메일, 주민번호, 카드, 계좌) + 인명 마스킹, 토큰 치환/복원
- [ ] 로깅 미들웨어와 Sentry에서 바디·`Authorization`·`Cookie` 스크러빙
- [ ] Rate Limit(Redis token bucket), `X-RateLimit-*` 헤더
- [ ] **레드팀 테스트셋** 50건 이상(인젝션/탈옥/유해 요청)으로 차단율 측정, 정상 입력 오탐률 ≤ 2% 확인

---

## Step 5. 말투 변환 & 감정 분석 API

- [ ] `GET /tone/options` (로케일별)
- [ ] `POST /tone/transform` JSON 응답 구현
- [ ] SSE 스트리밍: 증분 JSON 파서, `meta → analysis → red_flags → variant×3 → done` 이벤트
- [ ] 클라이언트 연결 종료 감지 시 LLM 스트림 취소
- [ ] keep-alive 주석(15초), `X-Accel-Buffering: no`
- [ ] 출력 검증: 스키마, red_flag 오프셋 보정, 온도 범위
- [ ] `POST /tone/analyze` (Light 티어)
- [ ] Opt-in 시 마스킹 로그 BackgroundTask 적재, 미동의 시 메트릭만 적재
- [ ] 골든셋 30건(페르소나 × 관계 × 언어)으로 의도 보존율·자연스러움 수동 평가

---

## Step 6. 답장 심리 해석기 API

- [ ] `POST /reply/interpret` 프롬프트 v1 (단정 금지, 확률·근거 제시, 조종성 답장 금지)
- [ ] JSON 응답 및 SSE(`interpretation → guide → reply×3 → done`)
- [ ] 대화 맥락 길이 제한(20턴, 3,000자) 및 화자 구분 데이터 블록화
- [ ] `disclaimer` i18n 적용
- [ ] 안전 시나리오 테스트(집착·감시·가스라이팅 유도 요청 거절)

---

## Step 7. 프론트엔드 핵심 화면

- [ ] 레이아웃, 네비게이션, 테마(라이트/다크)
- [ ] `ContextInput` (텍스트) + 스크린샷 업로드 → **온디바이스 OCR**(Tesseract.js) 프로토타입
- [ ] `DraftEditor` + 독소 하이라이트 오버레이(오프셋 기반)
- [ ] `PersonaSelector`, `RelationSelector`, `LanguageSelector`
- [ ] SSE 클라이언트(`fetch` + `ReadableStream`), 이벤트별 점진 렌더링
- [ ] `EmotionThermometer` (0–100°C 게이지, 변환 전후 비교, 구간 색상)
- [ ] `VariantCard` ×3 (복사/공유 → `/feedback`)
- [ ] 답장 해석기 화면(해석 카드, 가이드, 추천 답장)
- [ ] 히스토리(IndexedDB, 최대 500건, 전체 삭제)
- [ ] 설정(언어, 품질 로그 동의 토글, 연결 계정, 로그아웃, 탈퇴)
- [ ] 에러 코드별 사용자 메시지 및 재시도 UX

---

## Step 8. 다국어 (i18n)

- [ ] `locales/{ko,en,ja}/{common,auth,tone,errors}.json` 구성
- [ ] 백엔드 `Accept-Language` 협상과 에러 메시지 번역
- [ ] UI 언어와 변환 출력 언어 분리 설정
- [ ] 언어별 존댓말 매핑(`ko: haeyo/hapsyo/banmal`, `ja`, `en`) 프롬프트 반영
- [ ] 교차 언어 변환 골든셋(en→ko, ko→ja 등) 10건 평가
- [ ] 하드코딩 문자열 검출 lint 규칙 적용

---

## Step 9. 품질·보안 점검

- [ ] 테스트 커버리지 backend ≥ 80% (auth·guardrail·pii는 ≥ 90%)
- [ ] OWASP ASVS L1 체크리스트 자가 점검(인증, 세션, 입력 검증)
- [ ] 의존성 취약점 스캔, 비밀값 유출 스캔 통과
- [ ] 부하 테스트(k6): 동시 SSE 200 연결, TTFT p95 ≤ 1.5초 확인
- [ ] 비용 측정: 요청당 평균 비용 ≤ $0.004, 티어 분포 확인
- [ ] 개인정보 처리방침·이용약관 초안(수집 항목, 국외 이전, 보관 기간) 작성 및 법무 검토 요청

---

## Step 10. 1차 프로토타입 완성

- [ ] staging 배포(Docker 이미지, 환경변수/비밀값 주입)
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
