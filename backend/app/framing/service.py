"""Phase 4 — Saved Profiles CRUD Service."""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.framing.models import SavedProfile
from app.framing.schemas import (
    FramingConfig,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    RegionBox,
    WatermarkConfig,
)


def _to_read(p: SavedProfile) -> ProfileRead:
    """Convert ORM model to Pydantic read schema."""
    facecam_box: RegionBox | None = None
    gameplay_box: RegionBox | None = None
    watermark: WatermarkConfig | None = None

    if p.facecam_box_json:
        try:
            facecam_box = RegionBox(**json.loads(p.facecam_box_json))
        except Exception:
            pass

    if p.gameplay_box_json:
        try:
            gameplay_box = RegionBox(**json.loads(p.gameplay_box_json))
        except Exception:
            pass

    if p.watermark_path:
        watermark = WatermarkConfig(
            path=p.watermark_path,
            corner=p.watermark_corner,  # type: ignore[arg-type]
            scale=p.watermark_scale,
            opacity=p.watermark_opacity,
        )

    return ProfileRead(
        id=p.id,
        name=p.name,
        framing_mode=p.framing_mode,
        aspect_ratio=p.aspect_ratio,
        layout_template=p.layout_template,
        facecam_box=facecam_box,
        gameplay_box=gameplay_box,
        split_ratio=p.split_ratio,
        watermark=watermark,
        ollama_prompt=p.ollama_prompt,
        caption_style=p.caption_style,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


class ProfileService:
    @staticmethod
    async def list_profiles(session: AsyncSession) -> list[ProfileRead]:
        q = select(SavedProfile).order_by(SavedProfile.updated_at.desc())
        result = await session.execute(q)
        return [_to_read(p) for p in result.scalars().all()]

    @staticmethod
    async def create_profile(session: AsyncSession, payload: ProfileCreate) -> ProfileRead:
        profile_id = f"prof_{uuid.uuid4().hex[:12]}"
        p = SavedProfile(
            id=profile_id,
            name=payload.name,
            framing_mode=payload.framing_mode,
            aspect_ratio=payload.aspect_ratio,
            layout_template=payload.layout_template,
            split_ratio=payload.split_ratio,
            ollama_prompt=payload.ollama_prompt,
            caption_style=payload.caption_style,
        )

        if payload.facecam_box:
            p.facecam_box_json = payload.facecam_box.model_dump_json()
        if payload.gameplay_box:
            p.gameplay_box_json = payload.gameplay_box.model_dump_json()
        if payload.watermark:
            p.watermark_path = payload.watermark.path
            p.watermark_corner = payload.watermark.corner
            p.watermark_scale = payload.watermark.scale
            p.watermark_opacity = payload.watermark.opacity

        session.add(p)
        await session.commit()
        await session.refresh(p)
        return _to_read(p)

    @staticmethod
    async def get_profile(session: AsyncSession, profile_id: str) -> ProfileRead:
        q = select(SavedProfile).where(SavedProfile.id == profile_id)
        result = await session.execute(q)
        p = result.scalar_one_or_none()
        if not p:
            raise NotFoundError(f"Profile {profile_id} not found")
        return _to_read(p)

    @staticmethod
    async def update_profile(
        session: AsyncSession, profile_id: str, payload: ProfileUpdate
    ) -> ProfileRead:
        q = select(SavedProfile).where(SavedProfile.id == profile_id)
        result = await session.execute(q)
        p = result.scalar_one_or_none()
        if not p:
            raise NotFoundError(f"Profile {profile_id} not found")

        if payload.name is not None:
            p.name = payload.name
        if payload.framing_mode is not None:
            p.framing_mode = payload.framing_mode
        if payload.aspect_ratio is not None:
            p.aspect_ratio = payload.aspect_ratio
        if payload.layout_template is not None:
            p.layout_template = payload.layout_template
        if payload.split_ratio is not None:
            p.split_ratio = payload.split_ratio
        if payload.ollama_prompt is not None:
            p.ollama_prompt = payload.ollama_prompt
        if payload.caption_style is not None:
            p.caption_style = payload.caption_style
        if payload.facecam_box is not None:
            p.facecam_box_json = payload.facecam_box.model_dump_json()
        if payload.gameplay_box is not None:
            p.gameplay_box_json = payload.gameplay_box.model_dump_json()
        if payload.watermark is not None:
            p.watermark_path = payload.watermark.path
            p.watermark_corner = payload.watermark.corner
            p.watermark_scale = payload.watermark.scale
            p.watermark_opacity = payload.watermark.opacity

        p.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(p)
        return _to_read(p)

    @staticmethod
    async def delete_profile(session: AsyncSession, profile_id: str) -> None:
        q = select(SavedProfile).where(SavedProfile.id == profile_id)
        result = await session.execute(q)
        p = result.scalar_one_or_none()
        if not p:
            raise NotFoundError(f"Profile {profile_id} not found")
        await session.delete(p)
        await session.commit()

    @staticmethod
    async def profile_to_framing_config(session: AsyncSession, profile_id: str) -> FramingConfig:
        """Convert a saved profile into a FramingConfig ready for the FFmpeg builder."""
        profile = await ProfileService.get_profile(session, profile_id)
        from app.framing.schemas import FramingConfig, WatermarkConfig  # noqa
        return FramingConfig(
            framing_mode=profile.framing_mode,  # type: ignore[arg-type]
            aspect_ratio=profile.aspect_ratio,  # type: ignore[arg-type]
            layout_template=profile.layout_template,  # type: ignore[arg-type]
            facecam_box=profile.facecam_box,
            gameplay_box=profile.gameplay_box,
            split_ratio=profile.split_ratio,
            watermark=profile.watermark,
        )
