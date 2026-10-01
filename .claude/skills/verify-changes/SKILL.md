---
name: verify-changes
description: Run TalkSoft's lint, type-check, and test suites for backend (uv/ruff/mypy/pytest) and web (pnpm/eslint/tsc/vitest). Use before committing or after any code change in backend/ or web/.
---

# 변경 검증 절차

변경한 쪽만 돌려도 되지만, 커밋 전에는 둘 다 돌린다.

## 공통 준비

```bash
export PATH=~/.local/bin:~/.npm-global/bin:$PATH
unset VIRTUAL_ENV   # 루트 .venv(Python 3.9)가 uv 프로젝트 환경을 가리지 않게
```

- 셸이 zsh다. 반복문 변수로 `path`를 쓰지 않는다(zsh에서 `PATH`와 연결돼 명령을 못 찾게 된다).

## Backend (`backend/`)

```bash
cd backend
uv run ruff check --fix . && uv run ruff format .
uv run mypy app
uv run pytest --cov --cov-report=term

# 의존성 취약점 (uvx pip-audit만 실행하면 uvx 자신의 환경을 검사하므로 의미 없다)
uv export --format requirements-txt --no-emit-project > "$SCR/req.txt" && uvx pip-audit -r "$SCR/req.txt" --disable-pip
```

- ruff `S105`가 URL·알고리즘 이름 같은 상수에 오탐하면 해당 줄에만 `# noqa: S105`를 단다. 규칙을 전역으로 끄지 않는다.
- 커버리지 기준(PLAN Step 9): 전체 ≥ 80%, `auth/`·`llm/guardrails.py`·`privacy/` ≥ 90%.
- 실패하면 `uv run pytest -x <경로>::<테스트>`로 좁혀서 원인을 본다.

## Web (`web/`)

```bash
cd web
pnpm gen:api            # 백엔드 API가 바뀌었으면 타입을 다시 만든다(lib/api/schema.d.ts)
pnpm format && pnpm typecheck && pnpm lint && pnpm test
NEXT_TELEMETRY_DISABLED=1 pnpm build   # 라우트·서버 컴포넌트 오류는 build에서만 드러난다
pnpm audit --prod
```

## 완료 기준

- 위 명령이 모두 통과
- 새 로그 구문에 토큰·이메일·대화 원문이 없다 (로그 캡처 테스트가 있는 모듈은 그 테스트가 통과)
- API·DB가 바뀌었으면 `docs/API_SPEC.md`·`docs/DB_SCHEMA.md` 갱신, 완료 항목은 `docs/PLAN.md`에 체크
