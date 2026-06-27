"""TDX vipdoc file import collect strategy."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.sync.tia_collect.base import CollectStrategy, StrategyContext, StrategyResult


class TdxVipdocImportStrategy(CollectStrategy):
    mode = "file_import"

    def collect(self, ctx: StrategyContext) -> StrategyResult:
        from app.services.collectors.tdx_sidecar import TdxSidecarClient

        extra = ctx.extra
        base_url = extra.get("tdx_base_url") or (extra.get("source_config") or {}).get("base_url")
        if not base_url:
            return StrategyResult(message="TDX Sidecar base_url 未配置")

        cfg = extra.get("source_config") or {}
        client = TdxSidecarClient(
            str(base_url),
            extra.get("tdx_api_token") or cfg.get("api_token"),
        )
        period = "1d"
        if ctx.api_name.startswith("bar_"):
            period = ctx.api_name.replace("bar_", "")

        incremental = ctx.sync_ctx.batch_mode == "daily"
        last_sync = None
        if incremental:
            last_sync = ctx.start_date - timedelta(days=1)

        try:
            df, meta = client.vipdoc_import(
                period=period,
                start_date=ctx.start_date,
                end_date=ctx.end_date,
                incremental=incremental,
                last_sync_date=last_sync,
                limit_files=ctx.config.max_codes_per_run or None,
                install_root=cfg.get("install_root"),
                paths=cfg.get("paths"),
            )
        except Exception as exc:
            return StrategyResult(message=f"TDX vipdoc import failed: {exc}")

        import_mode = cfg.get("import_mode") or "file_first"
        if (df is None or df.empty) and import_mode == "file_first":
            df, net_meta = self._network_fallback(ctx, client, period)
            meta = {**(meta or {}), **(net_meta or {}), "fallback": "network"}

        api_calls = int((meta or {}).get("files_read") or (meta or {}).get("api_calls") or 0)
        result = self._upsert(ctx, df, api_calls=api_calls)
        if result.detail_json is not None:
            result.detail_json["source"] = (meta or {}).get("source", "file")
            result.detail_json["import_meta"] = meta
        return result

    def _network_fallback(
        self,
        ctx: StrategyContext,
        client,
        period: str,
    ) -> tuple[pd.DataFrame | None, dict]:
        from app.sync.tia_collect.stock_codes import resolve_stock_codes_for_collect

        codes = resolve_stock_codes_for_collect(ctx)
        if not codes:
            return None, {}
        cfg = ctx.extra.get("source_config") or {}
        batch = codes[: ctx.config.max_codes_per_run]
        try:
            df, meta = client.bars_batch(
                stock_codes=batch,
                period=period,
                start_date=ctx.start_date,
                end_date=ctx.end_date,
                install_root=cfg.get("install_root"),
                paths=cfg.get("paths"),
            )
            return df, meta
        except Exception:
            return None, {}


class TdxNetworkBarStrategy(CollectStrategy):
    """Explicit network-only bar collection."""

    mode = "tdx_network"

    def collect(self, ctx: StrategyContext) -> StrategyResult:
        from app.services.collectors.tdx_sidecar import TdxSidecarClient
        from app.sync.tia_collect.stock_codes import resolve_stock_codes_for_collect

        extra = ctx.extra
        cfg = extra.get("source_config") or {}
        base_url = extra.get("tdx_base_url") or cfg.get("base_url")
        if not base_url:
            return StrategyResult(message="TDX Sidecar base_url 未配置")
        client = TdxSidecarClient(str(base_url), extra.get("tdx_api_token") or cfg.get("api_token"))
        period = "1d"
        if ctx.api_name.startswith("bar_"):
            period = ctx.api_name.replace("bar_", "")
        codes = resolve_stock_codes_for_collect(ctx)
        if not codes:
            return StrategyResult(message="无股票代码列表")
        batch = codes[: ctx.config.max_codes_per_run]
        df, meta = client.bars_batch(
            stock_codes=batch,
            period=period,
            start_date=ctx.start_date,
            end_date=ctx.end_date,
            install_root=cfg.get("install_root"),
            paths=cfg.get("paths"),
        )
        api_calls = int((meta or {}).get("api_calls") or len(batch))
        result = self._upsert(ctx, df, api_calls=api_calls)
        if result.detail_json is not None:
            result.detail_json["source"] = "network"
        return result


class TdxConceptSnapshotStrategy(CollectStrategy):
    mode = "tdx_concept_snapshot"

    def collect(self, ctx: StrategyContext) -> StrategyResult:
        from app.services.collectors.tdx_sidecar import TdxSidecarClient

        extra = ctx.extra
        cfg = extra.get("source_config") or {}
        base_url = extra.get("tdx_base_url") or cfg.get("base_url")
        if not base_url:
            return StrategyResult(message="TDX Sidecar base_url 未配置")
        client = TdxSidecarClient(str(base_url), extra.get("tdx_api_token") or cfg.get("api_token"))
        trade_date = ctx.end_date
        payload = client.concept_catalog(
            trade_date,
            install_root=cfg.get("install_root"),
            paths=cfg.get("paths"),
        )
        if ctx.api_name == "concept_member":
            items = payload.get("concept_member_items") or []
        else:
            items = payload.get("concept_index_items") or []
        df = pd.DataFrame(items) if items else pd.DataFrame()
        result = self._upsert(ctx, df, api_calls=1)
        if result.detail_json is not None:
            result.detail_json["concept_map_source"] = payload.get("concept_map_source")
        return result
