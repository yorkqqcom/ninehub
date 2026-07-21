"""Platform settings and sync start date resolution."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.catalog.registry import get_data_type_entry
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.models.platform_setting import PlatformSetting
from app.schemas.platform import PlatformSettingsResponse, PlatformSettingsUpdate
from app.services.watch.watch_webhook_runtime import (
    env_webhook_configured,
    resolve_from_db_row,
)


class PlatformService:
    @staticmethod
    def mask_secret(token: str) -> str:
        if not token:
            return ""
        if len(token) <= 8:
            return "****"
        return token[:4] + "****" + token[-4:]

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

    def _to_response(self, setting: PlatformSetting) -> PlatformSettingsResponse:
        snap = resolve_from_db_row(setting)
        secret = (setting.watch_alert_webhook_secret or "").strip()
        url = (setting.watch_alert_webhook_url or "").strip() or None
        return PlatformSettingsResponse(
            sync_start_date=setting.sync_start_date,
            sync_type_overrides=setting.sync_type_overrides or {},
            env_sync_start_date=get_settings().sync_start_date,
            watch_alert_webhook_url=url,
            watch_alert_webhook_secret_masked=self.mask_secret(secret) if secret else None,
            watch_alert_webhook_secret_configured=bool(secret),
            watch_alert_webhook_signature_version=(
                setting.watch_alert_webhook_signature_version or "v2"
            ),
            watch_alert_webhook_active_source=snap.source,
            env_watch_alert_webhook_configured=env_webhook_configured(),
        )

    def webhook_snapshot_for_row(self, setting: PlatformSetting):
        return resolve_from_db_row(setting)

    async def get_settings(self, session: AsyncSession) -> PlatformSettingsResponse:
        setting = await self._get_or_create(session)
        return self._to_response(setting)

    def _apply_webhook_update(
        self,
        setting: PlatformSetting,
        body: PlatformSettingsUpdate,
    ) -> None:
        if body.watch_alert_webhook_clear:
            setting.watch_alert_webhook_url = None
            setting.watch_alert_webhook_secret = None
            setting.watch_alert_webhook_signature_version = "v2"
            return

        webhook_touched = any(
            v is not None
            for v in (
                body.watch_alert_webhook_url,
                body.watch_alert_webhook_secret,
                body.watch_alert_webhook_signature_version,
            )
        )
        if not webhook_touched:
            return

        if body.watch_alert_webhook_url is not None:
            raw_url = body.watch_alert_webhook_url.strip()
            if not raw_url:
                setting.watch_alert_webhook_url = None
            else:
                scheme_ok = raw_url.lower().startswith(("http://", "https://"))
                if not scheme_ok:
                    raise ValidationError(
                        "watch_alert_webhook_url must start with http:// or https://",
                        details={"field": "watch_alert_webhook_url"},
                    )
                if len(raw_url) > 512:
                    raise ValidationError(
                        "watch_alert_webhook_url must be at most 512 characters",
                        details={"field": "watch_alert_webhook_url"},
                    )
                setting.watch_alert_webhook_url = raw_url

        if body.watch_alert_webhook_secret is not None:
            secret = body.watch_alert_webhook_secret
            if secret == "":
                pass  # keep existing
            elif "****" in secret:
                raise ValidationError(
                    "watch_alert_webhook_secret looks masked; omit to keep or send new secret",
                    details={"field": "watch_alert_webhook_secret"},
                )
            else:
                stripped = secret.strip()
                if stripped and len(stripped) > 256:
                    raise ValidationError(
                        "watch_alert_webhook_secret must be at most 256 characters",
                        details={"field": "watch_alert_webhook_secret"},
                    )
                setting.watch_alert_webhook_secret = stripped or None

        if body.watch_alert_webhook_signature_version is not None:
            setting.watch_alert_webhook_signature_version = (
                body.watch_alert_webhook_signature_version
            )

        final_url = (setting.watch_alert_webhook_url or "").strip()
        final_secret = (setting.watch_alert_webhook_secret or "").strip()
        if final_url and not final_secret:
            raise ValidationError(
                "watch_alert_webhook_secret required when URL is set",
                details={"field": "watch_alert_webhook_secret"},
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
        self._apply_webhook_update(setting, body)
        await session.flush()
        await session.refresh(setting)
        return self._to_response(setting)

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
