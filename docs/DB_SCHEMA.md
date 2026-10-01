# 말랑톡 (TalkSoft) — 데이터베이스 설계

| 항목 | 내용 |
|---|---|
| 문서 버전 | v0.1 (초안) |
| DBMS | PostgreSQL 16 |
| 마이그레이션 | Alembic |
| 관련 문서 | [ARCHITECTURE.md](./ARCHITECTURE.md), [API_SPEC.md](./API_SPEC.md) |

---

## 1. 설계 원칙

1. **대화 원문 비저장**: 사용자 Context/Draft 원문을 담는 컬럼은 어디에도 없다. `transformation_logs`에는 PII를 마스킹한 텍스트만, 그것도 Opt-in일 때만 저장한다.
2. **식별자는 `(social_provider, provider_user_id)`**: 이메일은 바뀌거나 숨겨질 수 있으므로(애플 Relay) 식별에 쓰지 않는다.
3. **토큰은 해시로만**: 서비스 Refresh Token은 SHA-256 해시로 저장한다. 연결 해제에 필요한 제공자 토큰은 애플리케이션 레벨에서 암호화(AES-256-GCM, KMS 키)해 저장한다.
4. **PK는 UUID v7**: 시간순 정렬이 되고 추측하기 어렵다.
5. **Soft delete를 쓰지 않는다**(개인정보 테이블): 탈퇴하면 물리 삭제하고 `ON DELETE CASCADE`로 같이 지운다. 법정 보관 항목만 별도 테이블로 분리한다.
6. 모든 시각은 `timestamptz`(UTC).

> 요구사항 원문의 `Users.refresh_token`은 보안상 **별도 테이블 `refresh_tokens`로 분리하고 해시로 저장**한다. 이렇게 해야 다중 기기 세션과 Rotation, 재사용 탐지를 할 수 있다.

---

## 2. ERD

```
┌──────────────────┐ 1     N ┌──────────────────────┐
│      users       │────────▶│   social_accounts    │
│──────────────────│         │──────────────────────│
│ id (PK)          │         │ id (PK)              │
│ display_name     │         │ user_id (FK)         │
│ primary_email    │         │ social_provider      │
│ ui_locale        │         │ provider_user_id     │
│ status           │         │ email                │
│ ...              │         │ is_private_email     │
└──────┬───────────┘         └──────────────────────┘
       │ 1
       ├────────────N┌──────────────────────┐
       │             │    refresh_tokens    │
       │             └──────────────────────┘
       ├────────────N┌──────────────────────┐
       │             │    user_consents     │
       │             └──────────────────────┘
       └────────────N┌──────────────────────┐ N   1 ┌──────────────────┐
                     │  transformation_logs │──────▶│ prompt_templates │
                     └──────────┬───────────┘       └──────────────────┘
                                │ N
                                ▼ 1
                     ┌──────────────────────┐
                     │     tone_options     │
                     └──────────────────────┘
```

> `transformation_logs.user_id`는 탈퇴 시 `ON DELETE CASCADE`로 같이 삭제된다.

---

## 3. Enum 타입

```sql
CREATE TYPE social_provider   AS ENUM ('kakao', 'google', 'naver', 'apple');
CREATE TYPE user_status       AS ENUM ('active', 'suspended', 'pending_consent');
CREATE TYPE consent_type      AS ENUM ('terms_of_service', 'privacy_policy', 'age_over_14',
                                       'marketing', 'quality_log_collection');
CREATE TYPE llm_tier          AS ENUM ('light', 'heavy');
CREATE TYPE transform_kind    AS ENUM ('tone_transform', 'tone_analyze', 'reply_interpret');
CREATE TYPE log_status        AS ENUM ('success', 'guardrail_blocked', 'llm_error', 'schema_invalid');
```

---

## 4. 테이블 정의

### 4.1 `users` — 서비스 회원

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | uuid | PK | UUID v7 |
| display_name | varchar(50) | NULL | 닉네임(제공자에서 가져오거나 사용자가 수정) |
| primary_email | varchar(320) | NULL | 대표 이메일(애플 Relay 가능, 미제공 시 NULL) |
| ui_locale | varchar(10) | NOT NULL, DEFAULT 'ko' | UI 언어 |
| default_target_lang | varchar(10) | NOT NULL, DEFAULT 'ko' | 기본 변환 출력 언어 |
| plan | varchar(20) | NOT NULL, DEFAULT 'free' | free / premium |
| status | user_status | NOT NULL, DEFAULT 'pending_consent' | 필수 동의 전에는 pending_consent |
| last_login_at | timestamptz | NULL | |
| created_at | timestamptz | NOT NULL, DEFAULT now() | |
| updated_at | timestamptz | NOT NULL, DEFAULT now() | |

```sql
CREATE TABLE users (
    id                  uuid PRIMARY KEY,
    display_name        varchar(50),
    primary_email       varchar(320),
    ui_locale           varchar(10)  NOT NULL DEFAULT 'ko',
    default_target_lang varchar(10)  NOT NULL DEFAULT 'ko',
    plan                varchar(20)  NOT NULL DEFAULT 'free',
    status              user_status  NOT NULL DEFAULT 'pending_consent',
    last_login_at       timestamptz,
    created_at          timestamptz  NOT NULL DEFAULT now(),
    updated_at          timestamptz  NOT NULL DEFAULT now()
);
```

### 4.2 `social_accounts` — 제공자 계정 매핑

요구사항의 `social_provider`, `provider_user_id`, `email`을 이 테이블에 둔다. 한 사용자가 여러 제공자를 연결할 수 있다(1:N).

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | uuid | PK | |
| user_id | uuid | FK → users.id ON DELETE CASCADE, NOT NULL | |
| social_provider | social_provider | NOT NULL | kakao / google / naver / apple |
| provider_user_id | varchar(255) | NOT NULL | 제공자 고유 ID(`sub`, 네이버 `id`) |
| email | varchar(320) | NULL | 제공자가 준 이메일 |
| email_verified | boolean | NOT NULL, DEFAULT false | |
| is_private_email | boolean | NOT NULL, DEFAULT false | 애플 Private Relay 여부 |
| provider_refresh_token_enc | bytea | NULL | 연결 해제(revoke)용, **AES-GCM 암호화**. 애플만 사용 |
| scopes | text[] | NULL | 동의받은 scope |
| linked_at | timestamptz | NOT NULL, DEFAULT now() | |
| last_used_at | timestamptz | NULL | |

```sql
CREATE TABLE social_accounts (
    id                         uuid PRIMARY KEY,
    user_id                    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    social_provider            social_provider NOT NULL,
    provider_user_id           varchar(255) NOT NULL,
    email                      varchar(320),
    email_verified             boolean NOT NULL DEFAULT false,
    is_private_email           boolean NOT NULL DEFAULT false,
    provider_refresh_token_enc bytea,
    scopes                     text[],
    linked_at                  timestamptz NOT NULL DEFAULT now(),
    last_used_at               timestamptz,
    CONSTRAINT uq_provider_identity UNIQUE (social_provider, provider_user_id),
    CONSTRAINT uq_user_provider     UNIQUE (user_id, social_provider)
);
CREATE INDEX ix_social_accounts_user ON social_accounts(user_id);
```

### 4.3 `refresh_tokens` — 서비스 Refresh Token (해시 저장)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | uuid | PK | |
| user_id | uuid | FK → users.id ON DELETE CASCADE | |
| token_hash | char(64) | UNIQUE, NOT NULL | SHA-256(hex). **원문 저장 금지** |
| family_id | uuid | NOT NULL | 로그인 1회 = 1 family. 재사용 탐지 시 family 단위로 폐기 |
| parent_id | uuid | NULL | 회전 전 토큰 |
| device_info | varchar(200) | NULL | User-Agent 요약(전체 UA 저장 금지) |
| issued_at | timestamptz | NOT NULL | |
| expires_at | timestamptz | NOT NULL | 발급 + 14일 |
| revoked_at | timestamptz | NULL | |
| revoked_reason | varchar(30) | NULL | rotated / logout / reuse_detected / account_deleted |

```sql
CREATE TABLE refresh_tokens (
    id             uuid PRIMARY KEY,
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash     char(64) NOT NULL UNIQUE,
    family_id      uuid NOT NULL,
    parent_id      uuid REFERENCES refresh_tokens(id) ON DELETE SET NULL,
    device_info    varchar(200),
    issued_at      timestamptz NOT NULL DEFAULT now(),
    expires_at     timestamptz NOT NULL,
    revoked_at     timestamptz,
    revoked_reason varchar(30)
);
CREATE INDEX ix_refresh_tokens_family ON refresh_tokens(family_id);
CREATE INDEX ix_refresh_tokens_user_active ON refresh_tokens(user_id) WHERE revoked_at IS NULL;
```

**회전 로직**: `token_hash`로 조회한다.
- `revoked_at IS NULL AND expires_at > now()`이면 → 해당 행을 `revoked_reason='rotated'`로 바꾸고 같은 `family_id`로 새 행을 만든다.
- `revoked_at IS NOT NULL`(이미 회전된 토큰)이면 → **재사용 탐지**: 같은 `family_id` 전체를 `reuse_detected`로 폐기하고 401을 반환한다.
- 동시 요청 경합은 `SELECT ... FOR UPDATE`로 막는다.

### 4.4 `user_consents` — 약관/개인정보 동의 이력

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | uuid | PK | |
| user_id | uuid | FK → users.id ON DELETE CASCADE | |
| consent_type | consent_type | NOT NULL | |
| version | varchar(20) | NOT NULL | 약관 버전(예: `2026-10-01`) |
| agreed | boolean | NOT NULL | 동의/철회 |
| agreed_at | timestamptz | NOT NULL, DEFAULT now() | |

```sql
CREATE TABLE user_consents (
    id           uuid PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_type consent_type NOT NULL,
    version      varchar(20) NOT NULL,
    agreed       boolean NOT NULL,
    agreed_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_user_consents_latest ON user_consents(user_id, consent_type, agreed_at DESC);
```
- 이력은 append-only로 쌓는다. 현재 상태는 `(user_id, consent_type)`별 최신 행이다.
- `quality_log_collection`이 최신 기준 `agreed=true`일 때만 `transformation_logs`를 적재한다.

### 4.5 `tone_options` — 페르소나/말투 옵션 (다국어)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | serial | PK | |
| key | varchar(40) | NOT NULL | `affectionate`, `polite`, `polite_decline`, `concise_business`, `humorous`, `apology` |
| locale | varchar(10) | NOT NULL | 표시 언어 |
| display_name | varchar(50) | NOT NULL | "다정다감", "Polite" |
| description | varchar(200) | NOT NULL | UI 설명 |
| prompt_directive | text | NOT NULL | LLM에 넘기는 페르소나 지침(영문 권장, 정확성 목적) |
| default_tier | llm_tier | NOT NULL, DEFAULT 'light' | 라우팅 힌트 |
| icon | varchar(40) | NULL | |
| sort_order | smallint | NOT NULL, DEFAULT 0 | |
| is_active | boolean | NOT NULL, DEFAULT true | |

```sql
CREATE TABLE tone_options (
    id               serial PRIMARY KEY,
    key              varchar(40) NOT NULL,
    locale           varchar(10) NOT NULL,
    display_name     varchar(50) NOT NULL,
    description      varchar(200) NOT NULL,
    prompt_directive text NOT NULL,
    default_tier     llm_tier NOT NULL DEFAULT 'light',
    icon             varchar(40),
    sort_order       smallint NOT NULL DEFAULT 0,
    is_active        boolean NOT NULL DEFAULT true,
    CONSTRAINT uq_tone_key_locale UNIQUE (key, locale)
);
```

**시드 예시**
| key | locale | display_name | default_tier |
|---|---|---|---|
| affectionate | ko | 다정다감 | light |
| polite | ko | 공손 | light |
| polite_decline | ko | 정중한 거절 | heavy |
| concise_business | ko | 간결 업무체 | light |
| humorous | ko | 유머러스 | light |
| apology | ko | 진심 어린 사과 | heavy |

### 4.6 `prompt_templates` — 프롬프트 템플릿 (버전 관리)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | uuid | PK | |
| name | varchar(60) | NOT NULL | `tone_transform`, `tone_analyze`, `reply_interpret`, `guardrail_classify` |
| version | integer | NOT NULL | 1부터 증가 |
| locale | varchar(10) | NOT NULL, DEFAULT 'any' | 언어 특화 템플릿일 때 |
| system_prompt | text | NOT NULL | 시스템 지침(사용자 입력 자리 없음) |
| user_template | text | NOT NULL | 데이터 블록 템플릿(`{context}`, `{draft}` 등 자리표시자, 렌더 시 이스케이프) |
| output_schema | jsonb | NOT NULL | JSON Mode 출력 스키마 |
| model_tier | llm_tier | NOT NULL | |
| temperature | numeric(3,2) | NOT NULL, DEFAULT 0.7 | |
| max_tokens | integer | NOT NULL, DEFAULT 1200 | |
| is_active | boolean | NOT NULL, DEFAULT false | 이름+locale당 활성 1개 |
| rollout_percent | smallint | NOT NULL, DEFAULT 100 | A/B 실험용 |
| created_by | varchar(50) | NOT NULL | |
| created_at | timestamptz | NOT NULL, DEFAULT now() | |

```sql
CREATE TABLE prompt_templates (
    id              uuid PRIMARY KEY,
    name            varchar(60) NOT NULL,
    version         integer NOT NULL,
    locale          varchar(10) NOT NULL DEFAULT 'any',
    system_prompt   text NOT NULL,
    user_template   text NOT NULL,
    output_schema   jsonb NOT NULL,
    model_tier      llm_tier NOT NULL,
    temperature     numeric(3,2) NOT NULL DEFAULT 0.7,
    max_tokens      integer NOT NULL DEFAULT 1200,
    is_active       boolean NOT NULL DEFAULT false,
    rollout_percent smallint NOT NULL DEFAULT 100 CHECK (rollout_percent BETWEEN 0 AND 100),
    created_by      varchar(50) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_prompt_version UNIQUE (name, locale, version)
);
CREATE UNIQUE INDEX uq_prompt_active ON prompt_templates(name, locale) WHERE is_active;
```
- 활성 템플릿은 애플리케이션 시작 시 메모리에 캐시하고, 변경 시 Redis Pub/Sub로 무효화한다.
- 템플릿은 수정하지 않고(immutable) 새 버전을 추가한다 → 로그와 버전을 정확히 연결할 수 있다.

### 4.7 `transformation_logs` — 품질 분석 로그 (PII 마스킹, Opt-in)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | uuid | PK | |
| user_id | uuid | FK → users.id ON DELETE CASCADE, NULL | |
| request_id | varchar(40) | NOT NULL | X-Request-ID |
| kind | transform_kind | NOT NULL | |
| tone_option_key | varchar(40) | NULL | |
| prompt_template_id | uuid | FK → prompt_templates.id | |
| model_tier | llm_tier | NOT NULL | |
| model_id | varchar(60) | NOT NULL | 실제 사용 모델 |
| source_lang | varchar(10) | NULL | |
| target_lang | varchar(10) | NULL | |
| masked_context | text | NULL | **PII 마스킹 후 텍스트만**. Opt-in 시에만 |
| masked_draft | text | NULL | 상동 |
| masked_output | jsonb | NULL | 변환 결과(마스킹 후) |
| pii_types_detected | text[] | NULL | 예: `{PHONE,NAME}` (값 아님) |
| emotion_temperature | smallint | NULL | 0–100 |
| red_flag_count | smallint | NULL | |
| status | log_status | NOT NULL | |
| guardrail_score | numeric(4,3) | NULL | |
| input_tokens | integer | NULL | |
| output_tokens | integer | NULL | |
| cached_tokens | integer | NULL | 프롬프트 캐시 적중 토큰 |
| ttft_ms | integer | NULL | 첫 토큰 시간 |
| latency_ms | integer | NULL | |
| selected_variant | varchar(20) | NULL | 사용자가 복사한 variant(클라이언트 피드백) |
| created_at | timestamptz | NOT NULL, DEFAULT now() | |
| expires_at | timestamptz | NOT NULL | created_at + 90일 |

```sql
CREATE TABLE transformation_logs (
    id                  uuid PRIMARY KEY,
    user_id             uuid REFERENCES users(id) ON DELETE CASCADE,
    request_id          varchar(40) NOT NULL,
    kind                transform_kind NOT NULL,
    tone_option_key     varchar(40),
    prompt_template_id  uuid REFERENCES prompt_templates(id),
    model_tier          llm_tier NOT NULL,
    model_id            varchar(60) NOT NULL,
    source_lang         varchar(10),
    target_lang         varchar(10),
    masked_context      text,
    masked_draft        text,
    masked_output       jsonb,
    pii_types_detected  text[],
    emotion_temperature smallint CHECK (emotion_temperature BETWEEN 0 AND 100),
    red_flag_count      smallint,
    status              log_status NOT NULL,
    guardrail_score     numeric(4,3),
    input_tokens        integer,
    output_tokens       integer,
    cached_tokens       integer,
    ttft_ms             integer,
    latency_ms          integer,
    selected_variant    varchar(20),
    created_at          timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL DEFAULT (now() + interval '90 days')
);
CREATE INDEX ix_tlogs_created ON transformation_logs(created_at);
CREATE INDEX ix_tlogs_expires ON transformation_logs(expires_at);
CREATE INDEX ix_tlogs_user ON transformation_logs(user_id);
```

**적재 규칙**
| 조건 | `masked_*` 컬럼 | 메트릭 컬럼 |
|---|---|---|
| 품질 로그 동의 O | 마스킹 텍스트 저장 | 저장 |
| 품질 로그 동의 X | **NULL** | 저장(원문 없는 통계만) |
| Guardrail 차단 | **NULL** (동의 여부 무관) | 저장 |

**마스킹 예시**
```
원문:   "민수씨 010-1234-5678로 연락 주세요"
저장:   "[NAME_1]씨 [PHONE_1]로 연락 주세요"
pii_types_detected: {NAME, PHONE}
```

**파기**: 매일 03:00(KST) 배치 `DELETE FROM transformation_logs WHERE expires_at < now();`. 데이터가 커지면 월 단위 파티셔닝으로 바꾸고 파티션을 DROP한다.

---

## 5. 클라이언트 로컬 저장 구조 (서버 외)

서버에 저장하지 않는 히스토리는 클라이언트가 관리한다.

```ts
// IndexedDB: talksoft.history (웹) / SQLite (모바일)
interface HistoryItem {
  id: string;               // uuid
  kind: 'tone_transform' | 'reply_interpret';
  createdAt: string;        // ISO8601
  context?: string;         // 원문 (기기에만 저장)
  draft?: string;
  persona?: string;
  targetLang?: string;
  result: unknown;          // API 응답 그대로
  pinned: boolean;
}
```
- 최대 500건, 오래된 것부터 삭제. 로그아웃해도 유지하되 "로그아웃 시 삭제" 옵션을 제공한다.

---

## 6. 탈퇴 처리 트랜잭션

```
BEGIN;
  -- 1) 제공자 연결 해제 API 호출 (트랜잭션 외부, 실패 시 재시도 큐)
  -- 2) 법정 보관 대상이 있으면 별도 테이블로 이관 (현재 MVP에서는 없음)
  DELETE FROM users WHERE id = :user_id;   -- CASCADE: social_accounts, refresh_tokens,
                                            --          user_consents, transformation_logs
COMMIT;
```

---

## 7. 인덱스 및 성능 요약

| 쿼리 | 인덱스 |
|---|---|
| 로그인 시 제공자 계정 조회 | `uq_provider_identity (social_provider, provider_user_id)` |
| Refresh 검증 | `refresh_tokens.token_hash UNIQUE` |
| 재사용 탐지 시 family 폐기 | `ix_refresh_tokens_family` |
| 활성 프롬프트 조회 | `uq_prompt_active` (부분 인덱스) |
| 페르소나 목록 | `uq_tone_key_locale` |
| 로그 파기 배치 | `ix_tlogs_expires` |
