# TalkSoft Backend

FastAPI 기반 말랑톡 API 서버. 규칙은 루트 [CLAUDE.md](../CLAUDE.md), 설계는 [docs/](../docs/)를 따른다.

## 로컬 실행

```bash
cp .env.example .env
uv run python scripts/gen_dev_keys.py >> .env   # 기존 빈 JWT_*/DATA_ENCRYPTION_KEY 줄은 지운다
docker compose -f ../infra/docker-compose.yml up -d postgres redis
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## 검사

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run pytest --cov
```

테스트는 PostgreSQL/Redis 없이 SQLite(aiosqlite)와 fakeredis로 돌아간다.
