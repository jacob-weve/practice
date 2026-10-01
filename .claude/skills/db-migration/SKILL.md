---
name: db-migration
description: Create and verify an Alembic migration for the TalkSoft backend, including when no PostgreSQL server is running. Use whenever a SQLAlchemy model in backend/app/db/models changes.
---

# Alembic 마이그레이션 생성·검증

PostgreSQL이 떠 있지 않은 환경(에이전트 샌드박스 등)에서도 쓸 수 있는 절차다.

## 1. 모델 수정

- `backend/app/db/models/`에 모델을 추가·수정하고 `models/__init__.py`에서 export한다(Alembic이 메타데이터를 읽는 경로).
- SQLite 테스트와 호환되게 쓴다:
  - 배열: `app.db.base.TextArray` (PG `text[]` / SQLite JSON)
  - 부분 인덱스: `Index(..., postgresql_where=text("..."), sqlite_where=text("..."))` — 문자열을 그대로 넘기면 SQLite에서 깨진다.
  - enum: `_pg_enum(EnumCls, "type_name")` 패턴 (값 기준 저장)

## 2. 자동 생성 (임시 SQLite 대상)

```bash
cd backend && unset VIRTUAL_ENV && export PATH=~/.local/bin:$PATH
SCR=<스크래치 디렉터리>
rm -f $SCR/gen.db
DATABASE_URL="sqlite+aiosqlite:///$SCR/gen.db" uv run alembic upgrade head      # 기존 리비전까지 적용
DATABASE_URL="sqlite+aiosqlite:///$SCR/gen.db" uv run alembic revision --autogenerate -m "<설명>" --rev-id <다음번호 4자리>
```

## 3. 생성 결과를 반드시 손으로 고친다

- `postgresql.ARRAY(Text())` → `postgresql.ARRAY(sa.Text())` (import 누락으로 깨짐)
- `postgresql_where='...'` 문자열 → `sa.text('...')`
- 새 enum 타입을 만들었다면 `downgrade()` 끝에 타입 삭제 추가:
  ```python
  bind = op.get_bind()
  for enum_name in ("new_enum",):
      sa.Enum(name=enum_name).drop(bind, checkfirst=True)
  ```
- **같은 enum을 여러 테이블에서 쓰면** PostgreSQL에서 `CREATE TYPE`이 중복 실행돼 실패한다. 첫 테이블만 `sa.Enum(...)`을 두고, 나머지는
  `sa.Enum(..., name='x').with_variant(postgresql.ENUM(..., name='x', create_type=False), 'postgresql')`로 바꾼다 (예: `0002`의 `llm_tier`).
  오프라인 SQL에서 `CREATE TYPE x`가 한 번만 나오는지 확인한다.
- 데이터 변환이 필요한 변경(컬럼 타입 변경, NOT NULL 추가)은 autogenerate가 처리하지 않으므로 직접 작성한다.

## 4. 검증

```bash
export DATABASE_URL="sqlite+aiosqlite:///$SCR/gen.db"
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run alembic check                       # "No new upgrade operations detected." 이어야 함
DATABASE_URL="postgresql+asyncpg://x:y@localhost/z" uv run alembic upgrade head --sql | less
```

마지막 명령은 DB 연결 없이 PostgreSQL DDL을 출력한다. `CREATE TYPE`, `TEXT[]`, `WHERE` 부분 인덱스, FK `ON DELETE`가 의도대로인지 확인한다.

## 5. 마무리

- `docs/DB_SCHEMA.md` 갱신
- 마이그레이션은 별도 커밋 (`feat(db): ...`)
- PostgreSQL이 있는 환경에서 `alembic upgrade head` 실제 적용은 PLAN에 미완료 항목으로 남겨 둔다
