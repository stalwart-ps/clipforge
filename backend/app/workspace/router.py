import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db_session
from app.workspace.models import WorkspaceConfig
from app.workspace.schemas import WorkspaceConfigPatch, WorkspaceConfigRead

router = APIRouter(prefix="/api/projects", tags=["workspace"])


@router.get("/{project_id}/workspace", response_model=WorkspaceConfigRead)
async def get_workspace(
    project_id: str, session: AsyncSession = Depends(get_db_session)
) -> WorkspaceConfigRead:
    row = await session.get(WorkspaceConfig, project_id)
    if not row:
        return WorkspaceConfigRead(
            project_id=project_id,
            layout_config={},
            caption_config={},
            updated_at="",
        )

    layout_cfg = {}
    if row.layout_config_json:
        try:
            layout_cfg = json.loads(row.layout_config_json)
        except Exception:
            layout_cfg = {}

    caption_cfg = {}
    if row.caption_config_json:
        try:
            caption_cfg = json.loads(row.caption_config_json)
        except Exception:
            caption_cfg = {}

    export_cfg = {}
    if getattr(row, "export_config_json", None):
        try:
            export_cfg = json.loads(row.export_config_json)
        except Exception:
            export_cfg = {}

    return WorkspaceConfigRead(
        project_id=row.project_id,
        layout_config=layout_cfg,
        caption_config=caption_cfg,
        export_config=export_cfg,
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.patch("/{project_id}/workspace", response_model=WorkspaceConfigRead)
async def patch_workspace(
    project_id: str,
    payload: WorkspaceConfigPatch,
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceConfigRead:
    row = await session.get(WorkspaceConfig, project_id)
    if not row:
        row = WorkspaceConfig(
            project_id=project_id,
            layout_config_json="{}",
            caption_config_json="{}",
            export_config_json="{}",
        )
        session.add(row)

    if payload.layout_config is not None:
        row.layout_config_json = json.dumps(payload.layout_config)
    if payload.caption_config is not None:
        row.caption_config_json = json.dumps(payload.caption_config)
    if payload.export_config is not None:
        row.export_config_json = json.dumps(payload.export_config)

    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)

    layout_cfg = {}
    if row.layout_config_json:
        try:
            layout_cfg = json.loads(row.layout_config_json)
        except Exception:
            layout_cfg = {}

    caption_cfg = {}
    if row.caption_config_json:
        try:
            caption_cfg = json.loads(row.caption_config_json)
        except Exception:
            caption_cfg = {}

    export_cfg = {}
    if getattr(row, "export_config_json", None):
        try:
            export_cfg = json.loads(row.export_config_json)
        except Exception:
            export_cfg = {}

    return WorkspaceConfigRead(
        project_id=row.project_id,
        layout_config=layout_cfg,
        caption_config=caption_cfg,
        export_config=export_cfg,
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )
