# 말랑톡 (TalkSoft) — 보안 자가 점검 (OWASP ASVS 4.0.3 L1 기준)

| 항목 | 내용 |
|---|---|
| 점검일 | 2026-10-01 |
| 범위 | `backend/` (FastAPI), `web/` (Next.js). 모바일 앱·인프라는 범위 밖 |
| 방법 | 코드 검토 + 자동 테스트로 확인. 침투 테스트는 하지 않음 |

상태: ✅ 충족(테스트로 확인) · ⚠️ 부분 충족 · ❌ 미충족 · ➖ 해당 없음

---

## V2 인증

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 2.1 | 비밀번호 정책 | ➖ | 비밀번호 없음. 소셜 로그인만 사용 |
| 2.2.1 | 무차별 대입 방지 | ✅ | `/auth/*` IP당 분당 20회 (`test_auth_rate_limit`) |
| 2.5 | 자격 증명 복구 | ➖ | 제공자에 위임 |
| 2.7/2.8 | OTP·대체 인증 | ➖ | 없음 |
| — | OAuth 2.0 / OIDC | ✅ | 서버 측 PKCE(S256) 바인딩, 1회용 `state`, `nonce`, id_token 서명·`iss`·`aud`·`exp` 검증 (`test_auth_login.py`의 거부 테스트 9종) |
| — | redirect_uri 고정 | ✅ | 화이트리스트 + 인가 요청 때와 같은 값인지 확인 (`test_redirect_uri_must_match_the_authorize_request`) |
| — | 계정 자동 병합 금지 | ✅ | 같은 이메일이라도 다른 사용자 (`test_same_email_on_different_providers_is_not_merged`) |

## V3 세션 관리

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 3.1.1 | URL에 세션 토큰 금지 | ✅ | 토큰은 헤더·바디·쿠키로만. 콜백 페이지는 인가 코드를 주소창에서 즉시 지움 |
| 3.2.1 | 로그인 시 새 세션 | ✅ | 로그인마다 새 refresh token family |
| 3.2.3 | 토큰 저장 위치 | ✅ | 웹: Access는 메모리, Refresh는 `HttpOnly; Secure; SameSite=Strict` 쿠키. `localStorage` 미사용 |
| 3.3.1 | 로그아웃 시 무효화 | ✅ | `test_logout_revokes_family` |
| 3.3.2 | 세션 수명 | ✅ | Access 15분, Refresh 14일 고정 |
| 3.4 | 쿠키 속성 | ✅ | `HttpOnly`, `SameSite=Strict`, `Path=/api/v1/auth`, 운영 `Secure` (`COOKIE_SECURE`) |
| 3.5.3 | 토큰 서명 검증 | ✅ | RS256 고정(`algorithms` 명시), `none` 불가 |
| — | Refresh 재사용 탐지 | ✅ | family 전체 폐기 (`test_refresh_rotates_and_detects_reuse`) |
| — | 쿠키 기반 refresh의 CSRF | ✅ | `X-Requested-With: talksoft` 필수 + `SameSite=Strict` |

## V4 접근 제어

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 4.1.1 | 서버 측 접근 제어 | ✅ | 모든 기능 API는 `ActiveUser` 의존성 (동의 미완료 → 403) |
| 4.2.1 | IDOR 방지 | ✅ | 피드백은 본인 로그에만 기록 (`test_feedback_marks_selected_variant_only_for_owner`) |
| 4.3 | 관리자 기능 | ➖ | 없음 |

## V5 입력 검증·출력 인코딩

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 5.1.3 | 서버 측 입력 검증 | ✅ | Pydantic `extra="forbid"`, 길이 상한, enum 화이트리스트 |
| 5.1.4 | 구조화 데이터 검증 | ✅ | LLM 출력도 조각별·최종 스키마 검증 |
| 5.2 | 정제 | ✅ | NFC 정규화, 제로폭·제어 문자 제거 |
| 5.3.3 | XSS 방지 | ✅ | React 자동 이스케이프. `dangerouslySetInnerHTML` 미사용 |
| 5.3.4 | SQL 인젝션 | ✅ | SQLAlchemy 바인딩 파라미터만 사용 |
| — | 프롬프트 인젝션 | ⚠️ | 규칙 + 분류 모델 + 데이터 블록 격리 + 카나리아. **실제 모델 차단율 미측정** (`tests/redteam -m live`) |

## V7 오류 처리·로깅

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 7.1.1 | 로그에 자격 증명 금지 | ✅ | 키 이름·JWT·Bearer·이메일 패턴 스크러빙. 로그 유출 테스트 (`test_logs_never_contain_tokens_or_emails`, `test_app_logs_never_contain_message_text`) |
| 7.1.2 | 로그에 민감 데이터 금지 | ✅ | 대화 원문은 로그·DB 어디에도 없음. 품질 로그는 동의 + 마스킹 후에만 |
| 7.4.1 | 일반화된 오류 메시지 | ✅ | `code` + 번역 메시지만. 스택·제공자 원문·검증 실패 사유 미노출 |
| — | 보안 이벤트 기록 | ✅ | `security.refresh_reuse`, `guardrail.blocked`(유형·점수·해시만), `guardrail.canary_leak` |

## V8 데이터 보호

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 8.2.1 | 민감 응답 캐시 금지 | ✅ | 모든 API 응답 `Cache-Control: no-store`(SSE는 `no-cache`) (`test_api_responses_are_not_cacheable`) |
| 8.3.4 | 민감 데이터 식별·보호 | ✅ | Refresh는 SHA-256 해시만, 제공자 토큰은 AES-256-GCM |
| — | 보관 기간 | ✅ | 품질 로그 90일 후 파기 배치 (`app.jobs purge-logs`) |

## V9 통신

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 9.1.1 | TLS | ⚠️ | 리버스 프록시에서 TLS 종료 예정. **인프라 미구성** |

## V10 악성 코드·의존성 / V14 설정

| ASVS | 요구 | 상태 | 근거 |
|---|---|---|---|
| 14.2.1 | 의존성 취약점 | ✅ | pip-audit, pnpm audit 0건 (2026-10-01). CI에서 매번 검사 |
| 14.3.2 | 디버그 비활성 | ✅ | 운영에서 `/docs`, `/openapi.json` 끔 |
| 14.4 | 보안 헤더 | ⚠️ | 웹: `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`. **CSP 미설정** |
| 14.5.3 | CORS | ✅ | 허용 오리진 명시 + `allow_credentials` (와일드카드 없음) |
| — | 비밀값 관리 | ✅ | `.env` gitignore, gitleaks(pre-commit·CI) |

---

## 남은 조치 (우선순위 순)

1. 실제 분류 모델로 레드팀 차단율 측정 (목표 ≥ 95%, 오탐 ≤ 2%)
2. 웹 Content-Security-Policy 설정 (OCR용 jsdelivr·wasm 허용 범위 포함)
3. TLS·WAF·IP 단위 전역 rate limit 등 인프라 구성
4. 외부 침투 테스트 (출시 전)
