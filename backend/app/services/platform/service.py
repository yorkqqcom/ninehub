"""Platform settings and sync start date resolution."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.catalog.registry import get_data_type_entry
from app.core.config import get_settings
from app.models.platform_setting import PlatformSetting
from app.schemas.platform import PlatformSettingsResponse, PlatformSettingsUpdate


class PlatformService:
    async def _get_or_create(self, session: AsyncSession) -> PlatformSetting:
        result = await session.execute(select(PlatformSetting).limit(1))
        setting = result.scalar_one_or_none()
        if setting is None:
            settings = get_settings()
            setting = PlatformSetting(
                sync_start_date=settings.sync_start_date,
                sync_type_overrides={},
            )
            session.add(setting)
            await session.flush()
            await session.refresh(setting)
        return setting

    async def get_settings(self, session: AsyncSession) -> PlatformSettingsResponse:
        setting = await self._get_or_create(session)
        env_date = get_settings().sync_start_date
        return PlatformSettingsResponse(
            sync_start_date=setting.sync_start_date,
            sync_type_overrides=setting.sync_type_overrides or {},
            env_sync_start_date=env_date,
        )

    async def update_settings(
        self,
        session: AsyncSession,
        body: PlatformSettingsUpdate,
    ) -> PlatformSettingsResponse:
        setting = await self._get_or_create(session)
        if body.sync_start_date is not None:
            setting.sync_start_date = body.sync_start_date
        if body.sync_type_overrides is not None:
            setting.sync_type_overrides = body.sync_type_overrides
        await session.flush()
        await session.refresh(setting)
        return await self.get_settings(session)

    async def resolve_sync_start_date(
        self,
        session: AsyncSession,
        data_type: str,
    ) -> str:
        setting = await self._get_or_create(session)
        global_date = setting.sync_start_date
        overrides = setting.sync_type_overrides or {}
        if data_type in overrides:
            return max(global_date, overrides[data_type])
        entry = get_data_type_entry(data_type)
        if entry and entry.sync_start_date_override:
            return max(global_date, entry.sync_start_date_override)
        return global_date

    def resolve_sync_start_date_sync(self, session: Session, data_type: str) -> str:
        from sqlalchemy import select
        from sqlalchemy.orm import Session as OrmSession

        result = session.execute(select(PlatformSetting).limit(1))
        setting = result.scalar_one_or_none()
        if setting is None:
            global_date = get_settings().sync_start_date
        else:
            global_date = setting.sync_start_date
            overrides = setting.sync_type_overrides or {}
            if data_type in overrides:
                return max(global_date, overrides[data_type])
        entry = get_data_type_entry(data_type)
        if entry and entry.sync_start_date_override:
            return max(global_date, entry.sync_start_date_override)
        return global_date
