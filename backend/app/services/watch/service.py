"""Watch profile CRUD / enable gate."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.watch import WatchCooldownState, WatchEngineGate, WatchProfile
from app.services.watch.config import default_config, validate_and_normalize_config
from app.services.watch.cooldown import clear_cooldown_state
from app.services.watch.hub import get_quote_hub


class WatchProfileService:
    async def ensure_default(self, session: AsyncSession, user_id: int) -> WatchProfile:
        result = await session.execute(
            select(WatchProfile)
            .where(WatchProfile.user_id == user_id, WatchProfile.name == "default")
            .order_by(WatchProfile.id.asc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        settings = get_settings()
        count = (
            await session.execute(
                select(func.count()).select_from(WatchProfile).where(WatchProfile.user_id == user_id)
            )
        ).scalar_one()
        if count >= settings.watch_max_profiles_per_user:
            raise ValidationError(f"每用户最多 {settings.watch_max_profiles_per_user} 个盯盘配置")
        row = WatchProfile(
            user_id=user_id,
            name="default",
            enabled=False,
            config_revision=0,
            config_json=default_config(),
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
                await self._ensure_gate(session)
        except IntegrityError:
            result = await session.execute(
                select(WatchProfile)
                .where(WatchProfile.user_id == user_id, WatchProfile.name == "default")
                .order_by(WatchProfile.id.asc())
                .limit(1)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing
            raise
        await session.commit()
        await session.refresh(row)
        return row

    async def list_profiles(self, session: AsyncSession, user_id: int) -> list[WatchProfile]:
        result = await session.execute(
            select(WatchProfile).where(WatchProfile.user_id == user_id).order_by(WatchProfile.id.asc())
        )
        return list(result.scalars().all())

    async def get_owned(self, session: AsyncSession, user_id: int, profile_id: int) -> WatchProfile:
        result = await session.execute(
            select(WatchProfile).where(WatchProfile.id == profile_id, WatchProfile.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            raise NotFoundError("profile not found")
        return row

    async def create(
        self, session: AsyncSession, user_id: int, *, name: str, config: dict[str, Any] | None = None
    ) -> WatchProfile:
        settings = get_settings()
        count = (
            await session.execute(
                select(func.count()).select_from(WatchProfile).where(WatchProfile.user_id == user_id)
            )
        ).scalar_one()
        if count >= settings.watch_max_profiles_per_user:
            raise ValidationError(f"每用户最多 {settings.watch_max_profiles_per_user} 个盯盘配置")
        cfg = validate_and_normalize_config(config or default_config())
        row = WatchProfile(
            user_id=user_id,
            name=(name or "profile")[:128],
            enabled=False,
            config_revision=0,
            config_json=cfg,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError as exc:
            raise ValidationError(f"配置名称已存在: {row.name}") from exc
        await session.commit()
        await session.refresh(row)
        return row

    async def delete(self, session: AsyncSession, user_id: int, profile_id: int) -> None:
        row = await self.get_owned(session, user_id, profile_id)
        await session.delete(row)
        await session.commit()
        get_quote_hub().invalidate_user(user_id)

    async def set_enabled(
        self, session: AsyncSession, user_id: int, profile_id: int, enabled: bool
    ) -> WatchProfile:
        settings = get_settings()
        await self._ensure_gate(session)
        gate = (
            await session.execute(select(WatchEngineGate).where(WatchEngineGate.id == 1).with_for_update())
        ).scalar_one()
        _ = gate
        row = await self.get_owned(session, user_id, profile_id)
        if enabled and not row.enabled:
            enabled_count = (
                await session.execute(
                    select(func.count())
                    .select_from(WatchProfile)
                    .where(WatchProfile.enabled.is_(True), WatchProfile.id != profile_id)
                )
            ).scalar_one()
            if enabled_count >= settings.watch_max_enabled_profiles:
                raise ValidationError(
                    f"全局启用盯盘配置已达上限 {settings.watch_max_enabled_profiles}"
                )
        row.enabled = bool(enabled)
        await session.commit()
        await session.refresh(row)
        get_quote_hub().invalidate_user(user_id)
        return row

    async def put_config(
        self,
        session: AsyncSession,
        user_id: int,
        profile_id: int,
        *,
        config: dict[str, Any],
        expected_revision: int | None,
    ) -> WatchProfile:
        row = await self.get_owned(session, user_id, profile_id)
        if expected_revision is not None and int(expected_revision) != int(row.config_revision):
            raise ConflictError(
                f"config_revision 冲突: expected {expected_revision}, current {row.config_revision}",
            )
        cfg = validate_and_normalize_config(config)
        row.config_json = cfg
        flag_modified(row, "config_json")
        row.config_revision = int(row.config_revision) + 1
        await session.commit()
        await session.refresh(row)
        get_quote_hub().invalidate_user(user_id)
        return row

    async def clear_cooldown(self, session: AsyncSession, user_id: int, profile_id: int) -> None:
        await self.get_owned(session, user_id, profile_id)
        result = await session.execute(
            select(WatchCooldownState)
            .where(WatchCooldownState.profile_id == profile_id)
            .with_for_update()
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = WatchCooldownState(profile_id=profile_id, state_json=clear_cooldown_state())
            session.add(state)
        else:
            state.state_json = clear_cooldown_state()
            flag_modified(state, "state_json")
        await session.commit()

    async def _ensure_gate(self, session: AsyncSession) -> None:
        row = await session.get(WatchEngineGate, 1)
        if row is not None:
            return
        try:
            async with session.begin_nested():
                if await session.get(WatchEngineGate, 1) is None:
                    session.add(WatchEngineGate(id=1, note="singleton gate"))
                    await session.flush()
        except IntegrityError:
            pass
