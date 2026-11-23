from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    # Import all models to ensure they are registered with Base.metadata
    import app.settings.models  # noqa: F401
    import app.projects.models  # noqa: F401
    import app.framing.models   # noqa: F401
    import app.workspace.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Migration: Ensure Phase 3 columns exist on projects table in SQLite
        try:
            res = await conn.execute(text("PRAGMA table_info(projects)"))
            existing_cols = {row[1] for row in res.fetchall()}

            new_columns = {
                "transcript_json": "TEXT",
                "scene_cuts_json": "TEXT",
                "candidate_clips_json": "TEXT",
                "whisper_model_used": "VARCHAR(64)",
                "ollama_model_used": "VARCHAR(64)",
                # Phase 4
                "framing_config_json": "TEXT",
                "render_path": "VARCHAR(1024)",
                # Phase 6
                "ai_clip_recommendation": "TEXT",
            }

            for col_name, col_type in new_columns.items():
                if col_name not in existing_cols:
                    await conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}"))

            # Migration: Ensure export_config_json exists on workspace_config table
            res_ws = await conn.execute(text("PRAGMA table_info(workspace_config)"))
            ws_cols = {row[1] for row in res_ws.fetchall()}
            if "export_config_json" not in ws_cols:
                await conn.execute(text("ALTER TABLE workspace_config ADD COLUMN export_config_json TEXT DEFAULT '{}'"))
        except Exception as e:
            print(f"DB Migration Note: {e}")
