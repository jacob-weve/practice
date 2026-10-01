# 말랑톡 (TalkSoft) — RESTful API 명세서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 (초안) |
| Base URL | `https://api.talksoft.app/api/v1` |
| 인증 | `Authorization: Bearer <access_token>` (auth 엔드포인트 제외) |
| Content-Type | `application/json; charset=utf-8` |
| 관련 문서 | [ARCHITECTURE.md](./ARCHITECTURE.md), [DB_SCHEMA.md](./DB_SCHEMA.md) |

---

## 0. 공통 규약

### 0.1 공통 요청 헤더
| 헤더 | 필수 | 설명 |
|---|---|---|
| `Authorization` | 보호된 API | `Bearer <access_token>` |
| `Accept-Language` | 선택 | `ko`, `en`, `ja` — 에러 메시지·레이블 번역 |
| `Accept` | 선택 | `text/event-stream`이면 SSE 스트리밍, 기본은 `application/json` |
| `X-Request-ID` | 선택 | 없으면 서버가 생성해 응답 헤더로 돌려준다 |
| `X-Client-Platform` | 선택 | `web` / `ios` / `android` (Refresh Token 전달 방식 결정) |

### 0.2 공통 에러 응답

```json
{
  "error": {
    "code": "AUTH_INVALID_STATE",
    "message": "로그인 요청이 만료되었어요. 다시 시도해 주세요.",
    "request_id": "01J9Z3K8...",
    "details": {}
  }
}
```

**JSON Schema**
```json
{
  "$id": "ErrorResponse",
  "type": "object",
  "required": ["error"],
  "properties": {
    "error": {
      "type": "object",
      "required": ["code", "message", "request_id"],
      "properties": {
        "code": { "type": "string" },
        "message": { "type": "string" },
        "request_id": { "type": "string" },
        "details": { "type": "object" }
      }
    }
  }
}
```

### 0.3 에러 코드 표

| HTTP | code | 설명 |
|---|---|---|
| 400 | `VALIDATION_ERROR` | 요청 스키마 위반. `details.fields[]`에 `loc`, `type`만 담는다(입력값은 담지 않음) |
| 404 | `NOT_FOUND` | 없는 경로/리소스 |
| 400 | `AUTH_UNSUPPORTED_PROVIDER` | 지원하지 않는 provider |
| 400 | `AUTH_INVALID_REDIRECT_URI` | 화이트리스트에 없는 redirect_uri |
| 400 | `AUTH_INVALID_STATE` | state 불일치·만료·재사용 |
| 400 | `AUTH_PKCE_MISMATCH` | code_verifier 검증 실패 |
| 401 | `AUTH_PROVIDER_DENIED` | 제공자 토큰 교환 실패, 사용자 동의 취소 |
| 401 | `AUTH_ID_TOKEN_INVALID` | id_token 서명/iss/aud/exp/nonce 검증 실패 |
| 401 | `AUTH_TOKEN_EXPIRED` | Access Token 만료 → refresh 필요 |
| 401 | `AUTH_TOKEN_INVALID` | 토큰 위조·형식 오류 |
| 401 | `AUTH_REFRESH_INVALID` | Refresh Token 없음/만료/폐기 |
| 401 | `AUTH_REFRESH_REUSED` | Refresh Token 재사용 감지, 세션 전체 폐기됨 |
| 403 | `CONSENT_REQUIRED` | 필수 약관 미동의 |
| 403 | `ACCOUNT_SUSPENDED` | 이용 정지 |
| 409 | `ACCOUNT_LINK_CONFLICT` | 이미 다른 사용자에게 연결된 제공자 계정 |
| 413 | `INPUT_TOO_LONG` | 입력 길이 초과 |
| 422 | `INPUT_REJECTED` | Guardrail 차단(인젝션/유해 콘텐츠) |
| 429 | `RATE_LIMITED` | 요청 한도 초과 (`Retry-After` 헤더) |
| 502 | `LLM_UPSTREAM_ERROR` | LLM 제공사 오류(Fallback 실패) |
| 502 | `LLM_OUTPUT_INVALID` | LLM 출력 스키마 검증 실패(재시도 후) |
| 503 | `AUTH_PROVIDER_UNAVAILABLE` | OAuth 제공자 장애 |
| 500 | `INTERNAL_ERROR` | 처리되지 않은 서버 오류 |

### 0.4 공통 Enum
| 이름 | 값 |
|---|---|
| `Provider` | `kakao`, `google`, `naver`, `apple` |
| `Persona` | `affectionate`, `polite`, `polite_decline`, `concise_business`, `humorous`, `apology` |
| `Relation` | `work_superior`, `work_peer`, `client`, `partner`, `family`, `friend`, `acquaintance` |
| `Lang` | `ko`, `en`, `ja` (2차: `zh-CN`, `es`, `vi`) |
| `RedFlagType` | `sarcasm`, `blame`, `command`, `passive_aggressive`, `belittling`, `absolute`, `ambiguous`, `cold` |
| `Severity` | `low`, `medium`, `high` |

---

## 1. 인증 (Auth)

### 1.1 `GET /auth/authorize/{provider}` — 인가 URL 발급

PKCE `code_challenge`를 받아 서버가 `state`/`nonce`를 만들고 Redis에 저장(TTL 10분)한 뒤, 제공자 인가 URL을 돌려준다.

**Path**: `provider` ∈ `Provider`

**Query**
| 이름 | 필수 | 설명 |
|---|---|---|
| `code_challenge` | O | `BASE64URL(SHA256(code_verifier))`, 43자 |
| `code_challenge_method` | O | `S256` 고정 |
| `redirect_uri` | O | 사전 등록된 화이트리스트 URI만 허용 |

**Response 200**
```json
{
  "authorize_url": "https://kauth.kakao.com/oauth/authorize?client_id=...&response_type=code&redirect_uri=...&state=...&nonce=...&code_challenge=...&code_challenge_method=S256&scope=openid%20profile_nickname%20account_email",
  "state": "Zk8f...",
  "expires_in": 600
}
```

### 1.2 `POST /auth/login/{provider}` — 소셜 로그인 / 자동 가입

인가 코드를 토큰으로 교환하고 신원을 검증한 뒤 서비스 JWT를 발급한다. 처음 로그인한 사용자는 가입 처리하며, 필수 동의가 없으면 `status=pending_consent`로 응답한다.

**Path**: `provider` ∈ `kakao | google | naver | apple`

**Request JSON Schema**
```json
{
  "$id": "SocialLoginRequest",
  "type": "object",
  "required": ["code_verifier", "redirect_uri"],
  "oneOf": [
    { "required": ["code", "state"], "not": { "required": ["handoff"] } },
    { "required": ["handoff"], "not": { "required": ["code"] } }
  ],
  "additionalProperties": false,
  "properties": {
    "code":          { "type": "string", "minLength": 1, "maxLength": 2048 },
    "state":         { "type": "string", "minLength": 16, "maxLength": 128 },
    "handoff":       { "type": "string", "minLength": 16, "maxLength": 128,
                       "description": "Apple 웹 form_post 콜백(1.3)이 발급한 1회용 키. code·state 대신 사용" },
    "code_verifier": { "type": "string", "minLength": 43, "maxLength": 128,
                       "pattern": "^[A-Za-z0-9\\-._~]+$" },
    "redirect_uri":  { "type": "string", "format": "uri" },
    "apple_user": {
      "description": "Apple 최초 인가 시에만 전달되는 user JSON (name). Apple 전용",
      "type": "object",
      "properties": {
        "name": {
          "type": "object",
          "properties": {
            "firstName": { "type": "string", "maxLength": 50 },
            "lastName":  { "type": "string", "maxLength": 50 }
          }
        }
      }
    },
    "consents": {
      "description": "가입 화면에서 동의를 함께 보낼 때 사용(선택)",
      "type": "array",
      "items": { "$ref": "#/$defs/ConsentItem" }
    },
    "device_info": { "type": "string", "maxLength": 200 }
  },
  "$defs": {
    "ConsentItem": {
      "type": "object",
      "required": ["type", "version", "agreed"],
      "properties": {
        "type":    { "enum": ["terms_of_service", "privacy_policy", "age_over_14", "marketing", "quality_log_collection"] },
        "version": { "type": "string" },
        "agreed":  { "type": "boolean" }
      }
    }
  }
}
```

**Request 예시 (카카오)**
```json
{
  "code": "Dk3jf9...",
  "state": "Zk8f...",
  "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
  "redirect_uri": "https://talksoft.app/auth/callback/kakao",
  "device_info": "web/Chrome 128/macOS"
}
```

**Response 200 JSON Schema**
```json
{
  "$id": "AuthTokenResponse",
  "type": "object",
  "required": ["access_token", "token_type", "expires_in", "user", "is_new_user"],
  "properties": {
    "access_token":  { "type": "string" },
    "token_type":    { "const": "Bearer" },
    "expires_in":    { "type": "integer", "description": "초 단위, 900" },
    "refresh_token": { "type": "string", "description": "모바일(X-Client-Platform: ios/android)에서만 바디로 전달. 웹은 Set-Cookie" },
    "refresh_expires_in": { "type": "integer" },
    "is_new_user":   { "type": "boolean" },
    "user":          { "$ref": "#/$defs/UserProfile" },
    "required_consents": {
      "type": "array",
      "description": "status=pending_consent일 때 동의가 필요한 항목",
      "items": {
        "type": "object",
        "properties": {
          "type": { "type": "string" }, "version": { "type": "string" }, "url": { "type": "string" }
        }
      }
    }
  },
  "$defs": {
    "UserProfile": {
      "type": "object",
      "required": ["id", "status", "ui_locale", "linked_providers"],
      "properties": {
        "id":               { "type": "string", "format": "uuid" },
        "display_name":     { "type": ["string", "null"] },
        "email":            { "type": ["string", "null"] },
        "is_private_email": { "type": "boolean" },
        "status":           { "enum": ["active", "pending_consent", "suspended"] },
        "ui_locale":        { "type": "string" },
        "default_target_lang": { "type": "string" },
        "plan":             { "enum": ["free", "premium"] },
        "linked_providers": { "type": "array", "items": { "enum": ["kakao", "google", "naver", "apple"] } }
      }
    }
  }
}
```

**Response 예시 (애플 신규 가입, 웹)**
```http
HTTP/1.1 200 OK
Set-Cookie: ts_rt=8f2c...; Path=/api/v1/auth; HttpOnly; Secure; SameSite=Strict; Max-Age=1209600
```
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjIwMjYtMTAifQ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "is_new_user": true,
  "user": {
    "id": "0192f3a1-7c4e-7b2a-9d11-5e8b2f0c1a77",
    "display_name": "지은",
    "email": "x7k2abcd9@privaterelay.appleid.com",
    "is_private_email": true,
    "status": "pending_consent",
    "ui_locale": "ko",
    "default_target_lang": "ko",
    "plan": "free",
    "linked_providers": ["apple"]
  },
  "required_consents": [
    { "type": "terms_of_service", "version": "2026-10-01", "url": "https://talksoft.app/terms" },
    { "type": "privacy_policy",   "version": "2026-10-01", "url": "https://talksoft.app/privacy" },
    { "type": "age_over_14",      "version": "2026-10-01", "url": null }
  ]
}
```

**제공자별 서버 처리**
| provider | 토큰 교환 | 신원 확인 | 비고 |
|---|---|---|---|
| kakao | `POST https://kauth.kakao.com/oauth/token` | id_token(JWKS) 검증 | OIDC 활성화 필요 |
| google | `POST https://oauth2.googleapis.com/token` | id_token(JWKS) 검증 | `aud`=client_id |
| naver | `POST https://nid.naver.com/oauth2.0/token` | `GET https://openapi.naver.com/v1/nid/me` | OIDC 미지원, nonce 미사용 |
| apple | `POST https://appleid.apple.com/auth/token` (client_secret=ES256 JWT) | id_token(JWKS) 검증 | Relay 이메일, 이름 최초 1회 |

**에러**: `AUTH_UNSUPPORTED_PROVIDER`, `AUTH_INVALID_STATE`, `AUTH_PKCE_MISMATCH`, `AUTH_PROVIDER_DENIED`, `AUTH_ID_TOKEN_INVALID`, `AUTH_PROVIDER_UNAVAILABLE`, `ACCOUNT_SUSPENDED`

### 1.3 `POST /auth/callback/apple` — Apple form_post 콜백 (웹 전용)

Apple은 웹에서 `response_mode=form_post`로 콜백하므로 백엔드가 받는다.

**Request** (`application/x-www-form-urlencoded`): `code`, `state`, `id_token`, `user`(최초 1회)

**Response 303**: `Location: https://talksoft.app/auth/callback/apple?handoff=<1회용 코드, 60초>`
→ 프론트가 `{handoff, code_verifier, redirect_uri}`로 `POST /auth/login/apple`을 호출한다(`code`·`state` 대신 `handoff`). 서버는 `code`·`state`·`user`를 handoff 레코드에 임시 보관한다(Redis, TTL 60초, 1회용).
사용자가 취소하면 `Location: .../auth/callback/apple?error=access_denied`로 보낸다.

### 1.4 `POST /auth/refresh` — 토큰 재발급 (Rotation)

**Request**
- 웹: 바디 없음. `ts_rt` 쿠키 사용. CSRF 방지를 위해 `X-Requested-With: talksoft` 헤더 필수.
- 모바일:
```json
{
  "$id": "RefreshRequest",
  "type": "object",
  "required": ["refresh_token"],
  "additionalProperties": false,
  "properties": {
    "refresh_token": { "type": "string", "minLength": 32, "maxLength": 256 }
  }
}
```

**Response 200**: `AuthTokenResponse` 중 `access_token`, `token_type`, `expires_in`, `refresh_token`(모바일), `refresh_expires_in`만 반환. 웹은 새 `Set-Cookie`.
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "q9Xz...",
  "refresh_expires_in": 1209600
}
```

**에러**
| code | 클라이언트 처리 |
|---|---|
| `AUTH_REFRESH_INVALID` | 로그인 화면으로 이동 |
| `AUTH_REFRESH_REUSED` | 로컬 토큰 전부 삭제, "보안을 위해 다시 로그인해 주세요" 안내 |

### 1.5 `POST /auth/logout`
현재 Refresh Token(family)을 폐기한다. **Response 204**.

### 1.6 `POST /auth/consents` — 약관 동의 제출
```json
{
  "$id": "ConsentSubmitRequest",
  "type": "object",
  "required": ["consents"],
  "properties": {
    "consents": { "type": "array", "minItems": 1, "items": { "$ref": "SocialLoginRequest#/$defs/ConsentItem" } }
  }
}
```
**Response 200**: `{ "user": UserProfile }`. 필수 항목(`terms_of_service`, `privacy_policy`, `age_over_14`)이 모두 `agreed=true`면 `status=active`가 된다.

### 1.7 `POST /auth/link/{provider}` — 추가 제공자 계정 연결
요청은 1.2와 같다(인증 필요). 이미 다른 사용자에게 연결된 계정이면 `409 ACCOUNT_LINK_CONFLICT`.

### 1.8 `DELETE /users/me` — 회원 탈퇴
제공자 연결 해제(비동기 재시도 큐) 후 사용자 데이터를 물리 삭제한다. **Response 204**.

### 1.9 `GET /users/me` / `PATCH /users/me`
```json
{
  "$id": "UserUpdateRequest",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "display_name":        { "type": "string", "minLength": 1, "maxLength": 50 },
    "ui_locale":           { "enum": ["ko", "en", "ja"] },
    "default_target_lang": { "enum": ["ko", "en", "ja"] }
  }
}
```

### 1.10 `POST /auth/apple/notifications` — Apple 서버 간 알림 웹훅
요청 바디 `{"payload": "<Apple 서명 JWT>"}`. Apple JWKS로 서명·`iss`·`aud`를 검증하고 `email-disabled`, `email-enabled`, `consent-revoked`, `account-delete` 이벤트를 처리한다. **Response 200**.

---

## 2. 말투 변환 (Tone)

### 2.1 `GET /tone/options` — 페르소나 목록
**Response 200**
```json
{
  "personas": [
    { "key": "affectionate", "display_name": "다정다감", "description": "따뜻하고 애정 어린 말투", "icon": "heart" },
    { "key": "polite_decline", "display_name": "정중한 거절", "description": "관계를 지키면서 분명하게 거절", "icon": "hand" }
  ],
  "relations": ["work_superior", "work_peer", "client", "partner", "family", "friend", "acquaintance"],
  "languages": ["ko", "en", "ja"]
}
```

### 2.2 `POST /tone/transform` — 말투 변환 (One-shot: 감정 + 독소 + 변환 3종)

**Request JSON Schema**
```json
{
  "$id": "ToneTransformRequest",
  "type": "object",
  "required": ["draft", "persona", "target_lang"],
  "additionalProperties": false,
  "properties": {
    "context": {
      "type": "string", "maxLength": 2000,
      "description": "상대방이 보낸 메시지. 스크린샷은 클라이언트 OCR 후 텍스트로 전달"
    },
    "draft":       { "type": "string", "minLength": 1, "maxLength": 1000, "description": "사용자의 답장 초안" },
    "persona":     { "enum": ["affectionate", "polite", "polite_decline", "concise_business", "humorous", "apology"] },
    "relation":    { "enum": ["work_superior", "work_peer", "client", "partner", "family", "friend", "acquaintance"] },
    "target_lang": { "enum": ["ko", "en", "ja"] },
    "formality":   { "enum": ["auto", "high", "medium", "low"], "default": "auto" },
    "options": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "include_rationale": { "type": "boolean", "default": true },
        "emoji":             { "enum": ["none", "light", "rich"], "default": "light" }
      }
    }
  }
}
```

**Request 예시**
```json
{
  "context": "팀장님: 내일까지 보고서 수정본 가능할까요?",
  "draft": "아니 그걸 왜 지금 말해요. 내일은 절대 안돼요.",
  "persona": "polite_decline",
  "relation": "work_superior",
  "target_lang": "ko",
  "formality": "high"
}
```

**Response 200 JSON Schema** (`Accept: application/json`)
```json
{
  "$id": "ToneTransformResponse",
  "type": "object",
  "required": ["request_id", "intent", "emotion", "red_flags", "variants", "meta"],
  "properties": {
    "request_id": { "type": "string" },
    "intent": {
      "type": "object",
      "required": ["label", "confidence"],
      "properties": {
        "label": { "enum": ["accept", "decline", "request", "apology", "inform", "complain", "gratitude", "other"] },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
      }
    },
    "emotion": { "$ref": "#/$defs/Emotion" },
    "red_flags": { "type": "array", "items": { "$ref": "#/$defs/RedFlag" } },
    "variants": {
      "type": "array", "minItems": 1, "maxItems": 3,
      "items": {
        "type": "object",
        "required": ["kind", "text", "expected_temperature"],
        "properties": {
          "kind": { "enum": ["primary", "softer", "concise"] },
          "text": { "type": "string" },
          "expected_temperature": { "type": "integer", "minimum": 0, "maximum": 100 },
          "rationale": { "type": "string" }
        }
      }
    },
    "meta": {
      "type": "object",
      "properties": {
        "model_tier": { "enum": ["light", "heavy"] },
        "source_lang": { "type": "string" },
        "target_lang": { "type": "string" },
        "latency_ms": { "type": "integer" }
      }
    }
  },
  "$defs": {
    "Emotion": {
      "type": "object",
      "required": ["temperature", "labels"],
      "properties": {
        "temperature": { "type": "integer", "minimum": 0, "maximum": 100 },
        "zone": { "enum": ["cold", "calm", "warning", "danger"] },
        "labels": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["name", "score"],
            "properties": {
              "name": { "enum": ["anger", "frustration", "sadness", "anxiety", "joy", "affection", "neutral", "indifference"] },
              "score": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        }
      }
    },
    "RedFlag": {
      "type": "object",
      "required": ["start", "end", "text", "type", "severity"],
      "properties": {
        "start": { "type": "integer", "minimum": 0, "description": "draft 기준 문자 오프셋(UTF-16 code unit)" },
        "end":   { "type": "integer", "minimum": 0 },
        "text":  { "type": "string" },
        "type":  { "enum": ["sarcasm", "blame", "command", "passive_aggressive", "belittling", "absolute", "ambiguous", "cold"] },
        "severity": { "enum": ["low", "medium", "high"] },
        "reason": { "type": "string", "description": "UI 언어로 작성" },
        "suggestion": { "type": "string" }
      }
    }
  }
}
```

**Response 예시**
```json
{
  "request_id": "01J9Z4A1QW...",
  "intent": { "label": "decline", "confidence": 0.94 },
  "emotion": {
    "temperature": 82,
    "zone": "danger",
    "labels": [{ "name": "frustration", "score": 0.74 }, { "name": "anger", "score": 0.41 }]
  },
  "red_flags": [
    { "start": 0, "end": 13, "text": "아니 그걸 왜 지금 말해요", "type": "blame", "severity": "high",
      "reason": "상대를 탓하는 질문으로 읽혀요.", "suggestion": "조금 더 일찍 알았다면 좋았을 것 같아요" },
    { "start": 15, "end": 25, "text": "내일은 절대 안돼요", "type": "absolute", "severity": "medium",
      "reason": "'절대'가 단호하게 느껴져요.", "suggestion": "내일까지는 어려울 것 같습니다" }
  ],
  "variants": [
    { "kind": "primary", "expected_temperature": 42,
      "text": "팀장님, 말씀 주셔서 감사합니다. 다만 현재 진행 중인 업무 일정상 내일까지 수정본을 드리기는 어려울 것 같습니다. 모레 오전까지 가능할지 여쭤봐도 될까요?",
      "rationale": "거절 의사는 유지하고 대안 일정을 함께 제시했어요." },
    { "kind": "softer", "expected_temperature": 35,
      "text": "팀장님, 최대한 맞춰드리고 싶은데 내일까지는 일정이 빠듯해서 완성도가 걱정됩니다. 모레 오전까지 시간을 주시면 꼼꼼히 정리해서 드리겠습니다.",
      "rationale": "협조하려는 의지를 먼저 보여줬어요." },
    { "kind": "concise", "expected_temperature": 48,
      "text": "팀장님, 내일까지는 어렵고 모레 오전 제출 가능합니다.",
      "rationale": "핵심만 간결하게 전달했어요." }
  ],
  "meta": { "model_tier": "heavy", "source_lang": "ko", "target_lang": "ko", "latency_ms": 3820 }
}
```

**SSE 응답** (`Accept: text/event-stream`)
```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
X-Request-ID: 01J9Z4A1QW...

event: meta
data: {"request_id":"01J9Z4A1QW...","model_tier":"heavy"}

event: analysis
data: {"intent":{"label":"decline","confidence":0.94},"emotion":{"temperature":82,"zone":"danger","labels":[...]}}

event: red_flags
data: {"red_flags":[...]}

event: variant
data: {"index":0,"kind":"primary","text":"팀장님, ...","expected_temperature":42,"rationale":"..."}

event: variant
data: {"index":1,"kind":"softer", ...}

event: variant
data: {"index":2,"kind":"concise", ...}

event: done
data: {"usage":{"input_tokens":812,"output_tokens":540,"cached_tokens":600},"latency_ms":3820}
```
- 스트림 중 에러가 나면 `event: error` / `data: ErrorResponse.error` 후 연결을 종료한다.
- 스트림 시작 전 검증 오류(4xx)는 일반 JSON 에러 응답으로 반환한다.

**에러**: `VALIDATION_ERROR`, `INPUT_TOO_LONG`, `INPUT_REJECTED`, `CONSENT_REQUIRED`, `RATE_LIMITED`, `LLM_UPSTREAM_ERROR`, `LLM_OUTPUT_INVALID`

### 2.3 `POST /tone/analyze` — 감정 온도계 & 독소 감지만 (Light 티어)

**Request JSON Schema**
```json
{
  "$id": "ToneAnalyzeRequest",
  "type": "object",
  "required": ["text"],
  "additionalProperties": false,
  "properties": {
    "text":     { "type": "string", "minLength": 1, "maxLength": 1000 },
    "context":  { "type": "string", "maxLength": 2000 },
    "relation": { "enum": ["work_superior", "work_peer", "client", "partner", "family", "friend", "acquaintance"] }
  }
}
```

**Response 200**
```json
{
  "request_id": "01J9Z...",
  "emotion": { "temperature": 82, "zone": "danger", "labels": [{ "name": "frustration", "score": 0.74 }] },
  "red_flags": [ { "start": 0, "end": 13, "text": "...", "type": "blame", "severity": "high", "reason": "...", "suggestion": "..." } ]
}
```
(`emotion`, `red_flags`는 2.2의 `$defs`를 따른다.)

---

## 3. 답장 심리 해석 (Reply)

### 3.1 `POST /reply/interpret`

**Request JSON Schema**
```json
{
  "$id": "ReplyInterpretRequest",
  "type": "object",
  "required": ["message", "relation"],
  "additionalProperties": false,
  "properties": {
    "message": { "type": "string", "minLength": 1, "maxLength": 1000, "description": "해석할 상대방 메시지" },
    "conversation": {
      "type": "array", "maxItems": 20,
      "description": "앞뒤 대화(선택). 총 길이 3000자 제한",
      "items": {
        "type": "object",
        "required": ["speaker", "text"],
        "properties": {
          "speaker": { "enum": ["me", "them"] },
          "text":    { "type": "string", "maxLength": 500 },
          "sent_at": { "type": "string", "format": "date-time" }
        }
      }
    },
    "relation":    { "enum": ["work_superior", "work_peer", "client", "partner", "family", "friend", "acquaintance"] },
    "my_concern":  { "type": "string", "maxLength": 300, "description": "예: 화난 건지 궁금해요" },
    "target_lang": { "enum": ["ko", "en", "ja"], "default": "ko" }
  }
}
```

**Request 예시**
```json
{
  "message": "ㅇㅇ",
  "conversation": [
    { "speaker": "me", "text": "오늘 저녁에 영화 볼래? 7시쯤?" },
    { "speaker": "them", "text": "ㅇㅇ" }
  ],
  "relation": "partner",
  "my_concern": "기분이 안 좋은 건지 궁금해요"
}
```

**Response 200 JSON Schema**
```json
{
  "$id": "ReplyInterpretResponse",
  "type": "object",
  "required": ["request_id", "interpretations", "guide", "suggested_replies"],
  "properties": {
    "request_id": { "type": "string" },
    "message_emotion": { "$ref": "ToneTransformResponse#/$defs/Emotion" },
    "interpretations": {
      "type": "array", "minItems": 1, "maxItems": 3,
      "items": {
        "type": "object",
        "required": ["summary", "likelihood", "signals"],
        "properties": {
          "summary":    { "type": "string" },
          "likelihood": { "type": "number", "minimum": 0, "maximum": 1 },
          "signals":    { "type": "array", "items": { "type": "string" }, "description": "판단 근거(답장 길이, 이모지 부재 등)" }
        }
      }
    },
    "guide": {
      "type": "object",
      "required": ["summary"],
      "properties": {
        "summary":         { "type": "string" },
        "avoid":           { "type": "array", "items": { "type": "string" } },
        "check_points":    { "type": "array", "items": { "type": "string" } },
        "overthinking_warning": { "type": "boolean" }
      }
    },
    "suggested_replies": {
      "type": "array", "minItems": 3, "maxItems": 3,
      "items": {
        "type": "object",
        "required": ["style", "text"],
        "properties": {
          "style": { "enum": ["confirm", "empathize", "light_shift"] },
          "text":  { "type": "string" },
          "rationale": { "type": "string" }
        }
      }
    },
    "disclaimer": { "type": "string" }
  }
}
```

**Response 예시**
```json
{
  "request_id": "01J9Z5...",
  "message_emotion": { "temperature": 40, "zone": "calm", "labels": [{ "name": "neutral", "score": 0.68 }] },
  "interpretations": [
    { "summary": "단순히 바쁘거나 이동 중이라 짧게 수락했을 가능성", "likelihood": 0.6,
      "signals": ["질문에 대한 명확한 수락", "평소 답장 패턴 정보 없음"] },
    { "summary": "피곤하거나 기분이 가라앉아 있을 가능성", "likelihood": 0.3,
      "signals": ["이모지·추가 문장 없음"] },
    { "summary": "약속에 대한 기대가 크지 않을 가능성", "likelihood": 0.1, "signals": ["시간 제안에 반응 없음"] }
  ],
  "guide": {
    "summary": "'ㅇㅇ'은 수락 표현이고, 이것만으로 감정을 단정하기는 어려워요.",
    "avoid": ["'왜 이렇게 성의 없어?'처럼 따지는 말"],
    "check_points": ["평소에도 짧게 답하는지", "만났을 때 표정과 말투"],
    "overthinking_warning": true
  },
  "suggested_replies": [
    { "style": "confirm", "text": "좋아! 그럼 7시에 영화관 앞에서 보자 😊" },
    { "style": "empathize", "text": "오늘 많이 바빴어? 피곤하면 다음에 봐도 괜찮아!" },
    { "style": "light_shift", "text": "좋아~ 보고 싶은 영화 있어? 나 팝콘 쏠게 🍿" }
  ],
  "disclaimer": "AI 해석은 참고용이에요. 정확한 마음은 상대방과 직접 대화해서 확인해 주세요."
}
```
- SSE 지원: 이벤트 `meta` → `interpretation`(×N) → `guide` → `reply`(×3) → `done`.
- **안전 정책**: 상대를 조종·감시·비하하는 답장은 생성하지 않는다.

---

## 4. 피드백 & 기타

### 4.1 `POST /feedback` — 결과 채택/평가 (품질 지표, 원문 없음)
```json
{
  "$id": "FeedbackRequest",
  "type": "object",
  "required": ["request_id", "action"],
  "additionalProperties": false,
  "properties": {
    "request_id": { "type": "string" },
    "action":     { "enum": ["copied", "shared", "thumbs_up", "thumbs_down"] },
    "variant_kind": { "enum": ["primary", "softer", "concise", "confirm", "empathize", "light_shift"] },
    "reason":     { "enum": ["intent_changed", "too_formal", "too_casual", "unnatural", "other"] }
  }
}
```
**Response 204**

### 4.2 `GET /health` — 헬스 체크 (인증 불필요)
```json
{ "status": "ok", "version": "0.1.0", "db": "ok", "redis": "ok" }
```

---

## 5. Rate Limit

| 대상 | 무료 | 프리미엄 | 헤더 |
|---|---|---|---|
| `/tone/transform`, `/reply/interpret` | 30회/분, 300회/일 | 60회/분, 3,000회/일 | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` |
| `/tone/analyze` | 60회/분 | 120회/분 | 상동 |
| `/auth/*` | IP당 20회/분 | — | `Retry-After` |

---

## 6. 엔드포인트 요약

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| GET | `/auth/authorize/{provider}` | — | 인가 URL 발급(PKCE) |
| POST | `/auth/login/{provider}` | — | 소셜 로그인/가입 |
| POST | `/auth/callback/apple` | — | Apple form_post 콜백 (303 → handoff) |
| POST | `/auth/refresh` | Refresh | 토큰 재발급(Rotation) |
| POST | `/auth/logout` | O | 로그아웃 |
| POST | `/auth/consents` | O | 약관 동의 |
| POST | `/auth/link/{provider}` | O | 계정 연결 |
| POST | `/auth/apple/notifications` | Apple 서명 | Apple 서버 알림 |
| GET / PATCH | `/users/me` | O | 내 정보 |
| DELETE | `/users/me` | O | 탈퇴 |
| GET | `/tone/options` | O | 페르소나 목록 |
| POST | `/tone/transform` | O | 말투 변환 One-shot (JSON / SSE) |
| POST | `/tone/analyze` | O | 감정 온도계·독소 감지 |
| POST | `/reply/interpret` | O | 답장 심리 해석 (JSON / SSE) |
| POST | `/feedback` | O | 결과 피드백 |
| GET | `/health` | — | 헬스 체크 |
