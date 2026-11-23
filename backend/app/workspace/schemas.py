from typing import Any
from pydantic import Field
from app.core.schemas import APISchema


class WorkspaceConfigRead(APISchema):
    project_id: str
    layout_config: dict[str, Any] = Field(default_factory=dict)
    caption_config: dict[str, Any] = Field(default_factory=dict)
    export_config: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = ""


class WorkspaceConfigPatch(APISchema):
    layout_config: dict[str, Any] | None = None
    caption_config: dict[str, Any] | None = None
    export_config: dict[str, Any] | None = None
