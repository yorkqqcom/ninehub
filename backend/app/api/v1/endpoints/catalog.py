"""Catalog API endpoints."""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.deps import get_current_user
from app.core.exceptions import NotFoundError, ValidationError
from app.models.user import User
from app.schemas.catalog import (
    CatalogCoverageResponse,
    DataBrowseResponse,
    DataStandardDetailResponse,
    DataStandardExportResponse,
    DataStandardListResponse,
    DriftDetailResponse,
    DataTypeListResponse,
    QualitySuggestionsResponse,
)
from app.services.catalog.coverage_service import CatalogCoverageService
from app.services.catalog.data_standard_service import DataStandardService
from app.services.catalog.service import CatalogService

router = APIRouter()
_catalog = CatalogService()
_data_standards = DataStandardService()
_coverage = CatalogCoverageService()


@router.get(
    "/data-types",
    response_model=DataTypeListResponse,
    summary="数据类型列表",
    description=(
        "从 catalog registry 读取 data_type 列表，供任务 UI 与调度动态联动(D-07)。"
        "browse_only=true 时仅返回已激活且可查询类型，支持 q 搜索与 include_stats 行数统计。"
    ),
)
async def list_data_types(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    domain: Optional[str] = Query(None, description="按业务域筛选"),
    browse_only: bool = Query(False, description="仅返回 browse_enabled 且已激活类型"),
    q: Optional[str] = Query(None, description="搜索 data_type / label / table_name"),
    include_stats: bool = Query(False, description="为可查询表附加 row_count（较慢）"),
) -> DataTypeListResponse:
    return await _catalog.list_data_types(
        session,
        domain=domain,
        browse_only=browse_only,
        q=q,
        include_stats=include_stats,
    )


@router.get(
    "/data-standards",
    response_model=DataStandardListResponse,
    summary="TIA 提案 Schema 对照清单（汇总）",
    description=(
        "只读：按 TIA 提案列表展示接口字段与 L3 Schema 对照。"
        "治理操作（批准/激活）在 TIA 工作台提案 Tab 完成；"
        "Schema 持久化由 L3 infer_schema 步骤写入 tia_override。"
    ),
)
async def list_data_standards(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    domain: Optional[str] = Query(None, description="业务域筛选"),
    api: Optional[str] = Query(None, description="精确 api_name 筛选"),
    provider_id: Optional[str] = Query(None, description="数据源 provider_id 筛选"),
    drift_status: Optional[str] = Query(
        None, description="none | doc_drift | live_drift | ddl_drift"
    ),
    q: Optional[str] = Query(None, description="搜索 api_name / label / data_type"),
    min_coverage: Optional[float] = Query(None, ge=0, le=100, description="最低覆盖率 %"),
    ddl_ready: Optional[bool] = Query(None, description="是否可建表（标准校验通过）"),
    probe_status: Optional[str] = Query(
        None, description="configured | template | unconfigured"
    ),
    proposal_status: Optional[str] = Query(
        None, description="pending | approved | rejected | applied | failed"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> DataStandardListResponse:
    return await _data_standards.list_standards(
        session,
        domain=domain,
        api=api,
        provider_id=provider_id,
        drift_status=drift_status,
        q=q,
        min_coverage=min_coverage,
        ddl_ready=ddl_ready,
        probe_status=probe_status,
        proposal_status=proposal_status,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/data-standards/export",
    summary="批量导出 Schema 契约",
    description=(
        "只读：打包全部可导出接口的 JSON Schema 或 OpenAPI 片段。"
        "format=zip_json_schema|zip_openapi 返回 zip；format=openapi 返回聚合 openapi.json。"
    ),
)
async def export_data_standards_bundle(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    format: Literal["zip_json_schema", "zip_openapi", "openapi"] = Query(
        "zip_json_schema", alias="format"
    ),
    domain: Optional[str] = Query(None, description="业务域筛选"),
    provider_id: Optional[str] = Query(None, description="数据源 provider_id 筛选"),
    ddl_ready: Optional[bool] = Query(None, description="是否可建表"),
) -> Response:
    try:
        content, filename = await _data_standards.export_bundle(
            session,
            bundle_format=format,
            domain=domain,
            provider_id=provider_id,
            ddl_ready=ddl_ready,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    media_type = (
        "application/json"
        if format == "openapi"
        else "application/zip"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/data-standards/{api_name}/drift",
    response_model=DriftDetailResponse,
    summary="Schema 漂移明细",
    description="只读：文档 / 实测探针 / 物理表列与当前 schema 对照（admin 可读）。",
)
async def get_data_standard_drift(
    api_name: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> DriftDetailResponse:
    try:
        return await _data_standards.get_drift_detail(session, api_name)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get(
    "/data-standards/{api_name}/quality-suggestions",
    response_model=QualitySuggestionsResponse,
    summary="质检规则建议（只读）",
    description="基于 schema 唯一键与非空列建议 no_nulls 规则；创建仍须在 Quality 页完成。",
)
async def get_data_standard_quality_suggestions(
    api_name: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> QualitySuggestionsResponse:
    try:
        return await _data_standards.get_quality_suggestions(session, api_name)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get(
    "/data-standards/by-data-type/{data_type}/quality-suggestions",
    response_model=QualitySuggestionsResponse,
    summary="按 data_type 的质检规则建议",
)
async def get_quality_suggestions_by_data_type(
    data_type: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> QualitySuggestionsResponse:
    try:
        return await _data_standards.get_quality_suggestions_by_data_type(session, data_type)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get(
    "/data-standards/by-data-type/{data_type}/export",
    response_model=DataStandardExportResponse,
    summary="按 data_type 导出 JSON Schema",
)
async def export_data_standard_by_data_type(
    data_type: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    format: Literal["json_schema", "openapi"] = Query("json_schema", alias="format"),
) -> DataStandardExportResponse:
    try:
        return await _data_standards.export_schema_by_data_type(
            session, data_type, export_format=format
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/data-standards/{api_name}/export",
    response_model=DataStandardExportResponse,
    summary="导出 JSON Schema 契约",
    description="只读：将平台 schema 导出为 JSON Schema draft-07，供 Query Engine / 外部消费。",
)
async def export_data_standard(
    api_name: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    format: Literal["json_schema", "openapi"] = Query("json_schema", alias="format"),
) -> DataStandardExportResponse:
    try:
        return await _data_standards.export_schema(session, api_name, export_format=format)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/data-standards/{api_name}",
    response_model=DataStandardDetailResponse,
    summary="TIA 提案 Schema 对照（字段明细）",
    description="只读：单接口字段级对照（API 字段 ↔ 平台列），含 L3 建表就绪状态。",
)
async def get_data_standard_detail(
    api_name: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
) -> DataStandardDetailResponse:
    try:
        return await _data_standards.get_standard_detail(session, api_name)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get(
    "/coverage",
    response_model=CatalogCoverageResponse,
    summary="官网索引覆盖对照",
    description=(
        "只读对比本地 catalog（quota + override）与官方索引，无需触发 TIA 扫描 Job。"
        "index_source 与 TIA 扫描选项一致。"
    ),
)
async def catalog_coverage(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    index_scope: Literal["mixed", "stock_a"] = Query("mixed", description="索引范围"),
    index_source: Literal["auto", "document2", "doc14", "bundled", "live"] = Query(
        "auto", description="官方索引来源"
    ),
    sample_limit: int = Query(30, ge=1, le=100, description="样本列表上限"),
) -> CatalogCoverageResponse:
    return await _coverage.compute(
        session,
        index_scope=index_scope,
        index_source=index_source,
        sample_limit=sample_limit,
    )


@router.get(
    "/data/{data_type}",
    response_model=DataBrowseResponse,
    summary="浏览已激活事实表",
    description="TIA L3 落地后按 catalog 列动态分页查询。",
)
async def browse_data(
    data_type: str,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: Annotated[User, Depends(get_current_user)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    stock_code: str | None = Query(None),
    start_date: str | None = Query(None, description="YYYY-MM-DD"),
    end_date: str | None = Query(None, description="YYYY-MM-DD"),
) -> DataBrowseResponse:
    try:
        return await _catalog.browse_data(
            session,
            data_type,
            skip=skip,
            limit=limit,
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
