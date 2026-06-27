"""Data source CRUD, token masking, and connectivity verify."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.data_source import DataSource
from app.schemas.datasource import (
    DataSourceCreate,
    DataSourcePageResponse,
    DataSourceQuotaSummary,
    DataSourceResponse,
    DataSourceUpdate,
    DataSourceVerifyRequest,
    DataSourceVerifyResponse,
)
from app.services.tushare.source_quota import quota_from_config


class DataSourceService:
    def mask_token(self, token: str) -> str:
        if not token:
            return ""
        if len(token) <= 8:
            return "****"
        return token[:4] + "****" + token[-4:]

    def _mask_config(self, config: dict[str, Any]) -> dict[str, Any]:
        masked = dict(config)
        if "token" in masked and masked["token"]:
            masked["token"] = self.mask_token(str(masked["token"]))
        if "api_token" in masked and masked["api_token"]:
            masked["api_token"] = self.mask_token(str(masked["api_token"]))
        return masked

    def _normalize_config(
        self,
        provider: str,
        config: dict[str, Any],
        *,
        require_tushare_points: bool = False,
    ) -> dict[str, Any]:
        normalized = dict(config)
        if provider == "akshare":
            normalized.pop("account_points", None)
            normalized.pop("max_calls_per_minute", None)
            for key in ("base_url", "api_token", "install_root", "import_mode", "paths"):
                normalized.pop(key, None)
            return normalized
        if provider == "tdx":
            normalized.pop("account_points", None)
            normalized.pop("max_calls_per_minute", None)
            normalized.pop("token", None)
            if not normalized.get("base_url"):
                raise ValidationError(
                    "TDX 数据源须配置 Sidecar base_url",
                    details={"field": "config.base_url"},
                )
            normalized.setdefault("import_mode", "file_first")
            paths = normalized.get("paths")
            if paths is not None and hasattr(paths, "model_dump"):
                normalized["paths"] = paths.model_dump(exclude_none=True)
            return normalized
        if provider == "tushare":
            if require_tushare_points and normalized.get("account_points") is None:
                raise ValidationError(
                    "Tushare 数据源须配置 account_points（账户积分）",
                    details={"field": "config.account_points"},
                )
            return normalized
        return normalized

    def _quota_summary(self, source: DataSource) -> DataSourceQuotaSummary | None:
        if source.provider != "tushare":
            return None
        q = quota_from_config(source.config or {})
        return DataSourceQuotaSummary(**q)

    def _to_response(self, source: DataSource) -> DataSourceResponse:
        return DataSourceResponse(
            id=source.id,
            name=source.name,
            provider=source.provider,
            config=self._mask_config(source.config or {}),
            status=source.status,
            quota=self._quota_summary(source),
            created_at=source.created_at,
            updated_at=source.updated_at,
        )

    async def list_sources(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
    ) -> DataSourcePageResponse:
        total = (await session.execute(select(func.count()).select_from(DataSource))).scalar_one()
        result = await session.execute(
            select(DataSource).order_by(DataSource.id.desc()).offset(skip).limit(limit)
        )
        items = [self._to_response(s) for s in result.scalars().all()]
        page = (skip // limit) + 1 if limit else 1
        return DataSourcePageResponse(items=items, total=total, page=page, size=limit)

    async def get_source(self, session: AsyncSession, source_id: int) -> DataSourceResponse:
        source = await session.get(DataSource, source_id)
        if source is None:
            raise NotFoundError(f"Data source {source_id} not found")
        return self._to_response(source)

    async def create_source(
        self, session: AsyncSession, body: DataSourceCreate
    ) -> DataSourceResponse:
        config = body.config.model_dump(exclude_none=True)
        if body.config.paths is not None:
            config["paths"] = body.config.paths.model_dump(exclude_none=True)
        require_points = body.provider == "tushare"
        config = self._normalize_config(body.provider, config, require_tushare_points=require_points)
        source = DataSource(
            name=body.name,
            provider=body.provider,
            config=config,
            status=body.status,
        )
        session.add(source)
        await session.flush()
        await session.refresh(source)
        if body.provider == "tdx":
            self._sync_sidecar_config(config)
        return self._to_response(source)

    def _sync_sidecar_config(self, config: dict[str, Any]) -> None:
        from app.services.collectors.tdx_sidecar import TdxSidecarClient

        base_url = config.get("base_url")
        if not base_url:
            return
        payload: dict[str, Any] = {}
        if config.get("install_root"):
            payload["install_root"] = config["install_root"]
        paths = config.get("paths") or {}
        if isinstance(paths, dict):
            payload.update({k: v for k, v in paths.items() if v})
        if not payload:
            return
        try:
            client = TdxSidecarClient(str(base_url), config.get("api_token"))
            client.sync_tdx_config(payload)
        except Exception:
            pass

    async def update_source(
        self,
        session: AsyncSession,
        source_id: int,
        body: DataSourceUpdate,
    ) -> DataSourceResponse:
        source = await session.get(DataSource, source_id)
        if source is None:
            raise NotFoundError(f"Data source {source_id} not found")
        if body.name is not None:
            source.name = body.name
        if body.provider is not None:
            source.provider = body.provider
        if body.status is not None:
            source.status = body.status
        if body.config is not None:
            new_config = dict(source.config or {})
            incoming = body.config.model_dump(exclude_unset=True)
            if body.config.paths is not None:
                incoming["paths"] = body.config.paths.model_dump(exclude_none=True)
            if "token" in incoming and not incoming["token"]:
                incoming.pop("token")
            if "api_token" in incoming and not incoming["api_token"]:
                incoming.pop("api_token")
            if source.provider == "tushare" or body.provider == "tushare":
                if "account_points" in incoming and incoming["account_points"] is None:
                    incoming.pop("account_points")
            new_config.update(incoming)
            source.config = new_config
        provider = source.provider
        source.config = self._normalize_config(provider, source.config or {})
        if provider == "tdx":
            self._sync_sidecar_config(source.config or {})
        await session.flush()
        await session.refresh(source)
        return self._to_response(source)

    async def delete_source(self, session: AsyncSession, source_id: int) -> None:
        source = await session.get(DataSource, source_id)
        if source is None:
            raise NotFoundError(f"Data source {source_id} not found")
        await session.delete(source)

    async def verify(self, session: AsyncSession, body: DataSourceVerifyRequest) -> DataSourceVerifyResponse:
        token = body.token
        source: DataSource | None = None
        if body.source_id is not None:
            source = await session.get(DataSource, body.source_id)
            if source is None:
                raise NotFoundError(f"Data source {body.source_id} not found")
            cfg = source.config or {}
            body = DataSourceVerifyRequest(
                provider=source.provider,
                token=(cfg.get("token") or token) if source.provider != "tdx" else None,
                source_id=body.source_id,
                base_url=body.base_url or cfg.get("base_url"),
                api_token=body.api_token or cfg.get("api_token"),
                install_root=body.install_root or cfg.get("install_root"),
            )
        if body.provider == "akshare":
            return self._verify_akshare()
        if body.provider == "tdx":
            return self._verify_tdx(session, body)
        if not token:
            settings = get_settings()
            token = settings.tushare_token
        if not token:
            return DataSourceVerifyResponse(ok=False, message="未配置 token")
        if body.provider == "tushare":
            result = self._verify_tushare(token)
            cfg = (source.config or {}) if source else {}
            quota = DataSourceQuotaSummary(**quota_from_config(cfg))
            return DataSourceVerifyResponse(ok=result.ok, message=result.message, quota=quota)
        raise ValidationError(f"Unknown provider: {body.provider}")

    def _verify_akshare(self) -> DataSourceVerifyResponse:
        try:
            import akshare as ak

            df = ak.stock_info_a_code_name()
            if df is None or df.empty:
                return DataSourceVerifyResponse(ok=False, message="AkShare 返回空数据")
            return DataSourceVerifyResponse(ok=True, message="AkShare 连通正常")
        except ImportError:
            return DataSourceVerifyResponse(ok=True, message="akshare 未安装，跳过真实校验")
        except Exception as exc:
            return DataSourceVerifyResponse(ok=False, message=str(exc))

    def _verify_tdx(
        self,
        session: AsyncSession,
        body: DataSourceVerifyRequest,
    ) -> DataSourceVerifyResponse:
        from app.services.collectors.tdx_sidecar import TdxSidecarClient

        base_url = body.base_url
        api_token = body.api_token
        install_root = body.install_root
        if not base_url:
            return DataSourceVerifyResponse(ok=False, message="未配置 Sidecar base_url")
        try:
            client = TdxSidecarClient(str(base_url), api_token)
            health = client.health()
            status = client.vipdoc_status(install_root=install_root)
            return DataSourceVerifyResponse(
                ok=True,
                message=f"Sidecar 连通正常 ({health.get('backend', 'ok')})",
                probe=status,
            )
        except Exception as exc:
            return DataSourceVerifyResponse(ok=False, message=str(exc))

    async def probe_tdx(
        self,
        session: AsyncSession,
        body,
    ):
        from app.schemas.datasource import TdxProbeResponse
        from app.services.collectors.tdx_sidecar import TdxSidecarClient

        base_url = body.base_url
        api_token = body.api_token
        install_root = body.install_root
        paths = body.paths.model_dump(exclude_none=True) if body.paths else None
        if body.source_id is not None:
            source = await session.get(DataSource, body.source_id)
            if source is None:
                raise NotFoundError(f"Data source {body.source_id} not found")
            cfg = source.config or {}
            base_url = base_url or cfg.get("base_url")
            api_token = api_token or cfg.get("api_token")
            install_root = install_root or cfg.get("install_root")
            if not paths:
                paths = cfg.get("paths")
        if not base_url:
            return TdxProbeResponse(ok=False, message="未配置 base_url", status={})
        try:
            client = TdxSidecarClient(str(base_url), api_token)
            status = client.vipdoc_status(install_root=install_root, paths=paths)
            if install_root or paths:
                sync_payload = {"install_root": install_root}
                if paths:
                    sync_payload.update(paths)
                client.sync_tdx_config({k: v for k, v in sync_payload.items() if v})
            file_count = int(status.get("lday_file_count") or 0)
            ok = file_count > 0 or bool(status.get("install_root"))
            msg = "探测成功" if ok else "路径可访问但未发现 .day 文件"
            return TdxProbeResponse(ok=ok, message=msg, status=status)
        except Exception as exc:
            return TdxProbeResponse(ok=False, message=str(exc), status={})

    def _verify_tushare(self, token: str) -> DataSourceVerifyResponse:
        try:
            import tushare as ts

            pro = ts.pro_api(token)
            df = pro.trade_cal(exchange="SSE", start_date="20240101", end_date="20240105")
            if df is None or df.empty:
                return DataSourceVerifyResponse(ok=False, message="Tushare 返回空数据")
            return DataSourceVerifyResponse(ok=True, message="Tushare 连通正常")
        except ImportError:
            return DataSourceVerifyResponse(ok=True, message="tushare 未安装，跳过真实校验")
        except Exception as exc:
            return DataSourceVerifyResponse(ok=False, message=str(exc))
