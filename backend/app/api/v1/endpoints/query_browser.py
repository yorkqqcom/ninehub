"""Data Browser query API."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.query_browser import (
    BrowserAuditListResponse,
    BrowserExecuteRequest,
    BrowserExecuteResponse,
    BrowserExportRequest,
    BrowserExportResponse,
    BrowserMetaResponse,
    BrowserReadinessResponse,
    BrowserShareCreate,
    BrowserShareResponse,
    BrowserTemplateCreate,
    BrowserTemplateItem,
    BrowserTemplateResponse,
    BrowserTemplateUpdate,
    IndicatorRef,
    UniversePreviewRequest,
    UniversePreviewResponse,
    WatchlistCreate,
    WatchlistResponse,
    WatchlistUpdate,
)
from app.catalog.registry import DOMAINS, CATALOG_REGISTRY
from app.models.browser import BrowserWatchlist
from app.services.tia.override_service import TiaOverrideService
from app.services.query.browser_audit import BrowserAuditLogger
from app.services.query.browser_coverage import BrowserDataCoverage
from app.services.query.browser_export import BrowserExportService
from app.services.query.browser_query import BrowserQueryService
from app.services.query.browser_readiness import BrowserReadinessService
from app.services.query.browser_templates import BrowserTemplateService
from app.services.query.dimension_registry import DimensionRegistry
from app.services.query.indicator_registry import IndicatorRegistry
from app.services.query.browser_share import BrowserShareService
from app.services.query.universe_resolver import UniverseResolver

router = APIRouter()
_indicators = IndicatorRegistry()
_dimensions = DimensionRegistry()
_query = BrowserQueryService()
_universe = UniverseResolver()
_templates = BrowserTemplateService()
_export = BrowserExportService()
_share = BrowserShareService()
_coverage = BrowserDataCoverage()
_audit = BrowserAuditLogger()
_readiness = BrowserReadinessService()


async def _enriched_indicators(session: AsyncSession) -> list[IndicatorRef]:
    await TiaOverrideService().load_all_into_registry(session)
    refs = _indicators.list_indicators()
    table_names = {
        entry.table_name
        for ref in refs
        if (entry := CATALOG_REGISTRY.get(ref.data_type)) and entry.table_name
    }
    counts = await _coverage.get_table_row_counts(session, table_names)
    static_columns: dict[str, set[str]] = {}
    for ref in refs:
        if ref.freq != "static":
            continue
        entry = CATALOG_REGISTRY.get(ref.data_type)
        if entry and entry.table_name:
            static_columns.setdefault(entry.table_name, set()).add(ref.column_key)
    column_counts = await _coverage.get_column_non_null_counts(session, static_columns)
    return _indicators.enrich_with_coverage(counts, column_counts)


@router.get(
    "/meta",
    response_model=BrowserMetaResponse,
    summary="数据浏览器元数据",
    description="指标树、维度列表、系统模板。",
)
async def browser_meta(
    _: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> BrowserMetaResponse:
    system = [
        BrowserTemplateItem(
            id=str(t.get("id", "")),
            name=t.get("name", ""),
            description=t.get("description"),
            is_system=True,
            scope="system",
            payload=t.get("payload") or {},
        )
        for t in _indicators.system_templates()
    ]
    refs = await _enriched_indicators(session)
    return BrowserMetaResponse(
        indicator_tree=_indicators.build_tree(refs),
        indicators_flat=refs,
        dimensions=await _dimensions.list_dimensions(session),
        dimension_categories=_dimensions.category_labels(),
        system_templates=system,
        domains=[{"key": k, "label": v} for k, v in DOMAINS],
    )


@router.get(
    "/meta/indicators",
    response_model=list[IndicatorRef],
    summary="搜索指标",
)
async def search_indicators(
    _: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    q: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    available_only: bool = Query(False),
    data_ready_only: bool = Query(False),
) -> list[IndicatorRef]:
    refs = await _enriched_indicators(session)
    items = refs
    if available_only:
        items = [i for i in items if i.available]
    if data_ready_only:
        items = [i for i in items if i.data_ready]
    if domain:
        items = [i for i in items if i.domain == domain]
    if tags:
        tag_set = {t.strip() for t in tags.split(",") if t.strip()}
        items = [i for i in items if tag_set.intersection(i.tags)]
    if q:
        ql = q.lower()
        items = [
            i
            for i in items
            if ql in i.label.lower()
            or ql in i.id.lower()
            or (i.pinyin and ql in i.pinyin.lower())
            or any(ql in t.lower() for t in i.tags)
        ]
    return items


@router.get(
    "/readiness",
    response_model=BrowserReadinessResponse,
    summary="数据浏览器就绪状态",
    description="P0 门禁与 P1 申万/指数扩展表行数检查；含建议 bootstrap 脚本。",
)
async def browser_readiness(
    _: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> BrowserReadinessResponse:
    return await _readiness.check(session, extended=True)


@router.post(
    "/universe/preview",
    response_model=UniversePreviewResponse,
    summary="证券池预览",
)
async def universe_preview(
    body: UniversePreviewRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> UniversePreviewResponse:
    count, sample, warnings, is_estimate = await _universe.preview(
        session, body.universe, user.id
    )
    return UniversePreviewResponse(
        stock_count=count,
        sample_codes=sample,
        warnings=warnings,
        is_estimate=is_estimate,
    )


@router.post(
    "/execute",
    response_model=BrowserExecuteResponse,
    summary="执行宽表查询",
)
async def browser_execute(
    body: BrowserExecuteRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> BrowserExecuteResponse:
    return await _query.execute(session, body, user.id)


@router.post(
    "/export",
    response_model=BrowserExportResponse,
    summary="导出宽表",
)
async def browser_export(
    body: BrowserExportRequest,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> BrowserExportResponse:
    return await _export.export(session, body, user.id)


@router.get(
    "/exports/sync/{token}/download",
    summary="下载同步 xlsx 导出",
)
async def download_sync_export(
    token: str,
    _: Annotated[User, Depends(get_current_user)],
) -> FastAPIResponse:
    if not token.isalnum() or len(token) > 64:
        raise HTTPException(status_code=400, detail="无效 token")
    result = _export.read_sync_export_file(token)
    if result is None:
        raise HTTPException(status_code=404, detail="导出文件不存在或已过期")
    data, mime = result
    return FastAPIResponse(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="browser_{token[:8]}.xlsx"'},
    )


@router.get(
    "/exports/{job_id}/download",
    summary="下载异步导出文件",
)
async def download_export(
    job_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> FastAPIResponse:
    from app.services.platform.job_service import PlatformJobService

    jobs = PlatformJobService()
    job = await jobs.get(session, job_id)
    if job.created_by_id and job.created_by_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权下载该导出")
    if job.status != "success":
        raise HTTPException(status_code=404, detail="导出未完成")
    result = _export.read_export_file(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="导出文件不存在")
    data, mime = result
    fmt = (job.result_json or {}).get("format") or "csv"
    ext = "xlsx" if fmt == "xlsx" else "csv"
    return FastAPIResponse(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="browser_{job_id}.{ext}"'},
    )


@router.get(
    "/audit",
    response_model=BrowserAuditListResponse,
    summary="查询审计日志",
)
async def list_audit(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> BrowserAuditListResponse:
    return await _audit.list_audits(
        session, user.id, user.role == "admin", skip=skip, limit=limit
    )


@router.get(
    "/templates",
    response_model=list[BrowserTemplateResponse],
    summary="查询模板列表",
)
async def list_templates(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[BrowserTemplateResponse]:
    return await _templates.list_templates(session, user.id)


@router.post(
    "/templates",
    response_model=BrowserTemplateResponse,
    summary="保存用户模板",
)
async def create_template(
    body: BrowserTemplateCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> BrowserTemplateResponse:
    return await _templates.create(session, user.id, body)


@router.get(
    "/templates/{template_id}",
    response_model=BrowserTemplateResponse,
    summary="获取模板",
)
async def get_template(
    template_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> BrowserTemplateResponse:
    return await _templates.get(session, template_id, user.id)


@router.put(
    "/templates/{template_id}",
    response_model=BrowserTemplateResponse,
    summary="更新模板",
)
async def update_template(
    template_id: int,
    body: BrowserTemplateUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> BrowserTemplateResponse:
    return await _templates.update(
        session,
        template_id,
        user.id,
        name=body.name,
        payload=body.payload,
        description=body.description,
    )


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    summary="删除模板",
)
async def delete_template(
    template_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    is_admin = user.role == "admin"
    await _templates.delete(session, template_id, user.id, is_admin)
    return Response(status_code=204)


@router.get(
    "/watchlists",
    response_model=list[WatchlistResponse],
    summary="自选股列表",
)
async def list_watchlists(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[WatchlistResponse]:
    rows = (
        await session.execute(
            select(BrowserWatchlist).where(BrowserWatchlist.user_id == user.id)
        )
    ).scalars().all()
    return [
        WatchlistResponse(id=r.id, name=r.name, codes=list(r.codes_json or [])) for r in rows
    ]


@router.get(
    "/watchlists/{watchlist_id}",
    response_model=WatchlistResponse,
    summary="获取证券池",
)
async def get_watchlist(
    watchlist_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> WatchlistResponse:
    row = await session.get(BrowserWatchlist, watchlist_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="证券池不存在")
    return WatchlistResponse(id=row.id, name=row.name, codes=list(row.codes_json or []))


@router.post(
    "/watchlists",
    response_model=WatchlistResponse,
    summary="保存证券池",
)
async def create_watchlist(
    body: WatchlistCreate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> WatchlistResponse:
    codes = list(body.codes)
    if body.universe and not codes:
        codes = await _universe.resolve(session, body.universe, user.id)
    row = BrowserWatchlist(
        user_id=user.id,
        name=body.name,
        codes_json=codes,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return WatchlistResponse(id=row.id, name=row.name, codes=list(row.codes_json or []))


@router.put(
    "/watchlists/{watchlist_id}",
    response_model=WatchlistResponse,
    summary="更新证券池",
)
async def update_watchlist(
    watchlist_id: int,
    body: WatchlistUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> WatchlistResponse:
    row = await session.get(BrowserWatchlist, watchlist_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="证券池不存在")
    if body.name is not None:
        row.name = body.name
    if body.codes is not None:
        row.codes_json = body.codes
    await session.commit()
    await session.refresh(row)
    return WatchlistResponse(id=row.id, name=row.name, codes=list(row.codes_json or []))


@router.delete(
    "/watchlists/{watchlist_id}",
    status_code=204,
    summary="删除证券池",
)
async def delete_watchlist(
    watchlist_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    row = await session.get(BrowserWatchlist, watchlist_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="证券池不存在")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/share",
    response_model=BrowserShareResponse,
    summary="创建查询分享链接",
)
async def create_share(
    body: BrowserShareCreate,
    user: Annotated[User, Depends(get_current_user)],
) -> BrowserShareResponse:
    token = _share.create_token(body.payload)
    return BrowserShareResponse(share_token=token)


@router.get(
    "/share/{share_token}",
    summary="读取分享查询定义",
)
async def get_share(
    share_token: str,
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    payload = _share.get_payload(share_token)
    if payload is None:
        raise HTTPException(status_code=404, detail="分享链接无效或已过期")
    return payload
