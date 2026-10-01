"""백엔드 OpenAPI 스키마를 web/lib/api/openapi.json으로 내보낸다.

사용법: uv run python -m scripts.export_openapi  (보통은 web에서 pnpm gen:api로 실행한다)
"""

import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

OUT = Path(__file__).resolve().parents[2] / "web/lib/api/openapi.json"


def main() -> None:
    schema = create_app(Settings(app_env="local")).openapi()
    OUT.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
