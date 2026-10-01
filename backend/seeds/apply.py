"""기준 데이터를 멱등하게 넣는다.

사용법: uv run python -m seeds.apply
"""

import asyncio

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import PromptTemplate, ToneOption
from app.db.session import create_engine, create_sessionmaker
from seeds.catalog import PERSONAS, TEMPLATES, output_schema_for


async def apply_seeds(db: AsyncSession) -> None:
    existing = {
        (row.key, row.locale): row for row in (await db.execute(select(ToneOption))).scalars()
    }
    for order, persona in enumerate(PERSONAS):
        for locale, (display_name, description) in persona["names"].items():
            values = {
                "display_name": display_name,
                "description": description,
                "prompt_directive": persona["directive"],
                "default_tier": persona["tier"],
                "icon": persona["icon"],
                "sort_order": order,
                "is_active": True,
            }
            row = existing.get((persona["key"], locale))
            if row is None:
                db.add(ToneOption(key=persona["key"], locale=locale, **values))
            else:
                for field, value in values.items():
                    setattr(row, field, value)

    for tpl in TEMPLATES:
        found = await db.scalar(
            select(PromptTemplate.id).where(
                PromptTemplate.name == tpl["name"],
                PromptTemplate.locale == "any",
                PromptTemplate.version == tpl["version"],
            )
        )
        if found is not None:
            continue
        # 같은 이름의 이전 버전을 비활성화한 뒤 새 버전을 활성화한다.
        await db.execute(
            update(PromptTemplate)
            .where(PromptTemplate.name == tpl["name"], PromptTemplate.locale == "any")
            .values(is_active=False)
        )
        await db.flush()
        db.add(
            PromptTemplate(
                name=tpl["name"],
                version=tpl["version"],
                locale="any",
                system_prompt=tpl["system_prompt"],
                user_template=tpl["user_template"],
                output_schema=output_schema_for(tpl["name"]),
                model_tier=tpl["model_tier"],
                max_tokens=tpl["max_tokens"],
                is_active=True,
                created_by="seed",
            )
        )
    await db.commit()


async def main() -> None:
    engine = create_engine(get_settings().database_url)
    async with create_sessionmaker(engine)() as session:
        await apply_seeds(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
