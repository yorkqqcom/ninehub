"""TIA governance endpoints."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.database import get_async_session, get_sync_session
from app.core.exceptions import NotFoundError, ValidationError
from app.core.deps import RequireAdmin
from app.schemas.tia import (
    TiaDocAuthStatusResponse,
    TiaDocAuthUpdateRequest,
    TiaDocAuthVerifyResponse,
    TiaDocPagesSyncRequest,
    TiaDocPointsCoverageResponse,
    TIAScanJobResponse,
    TIAScanRequest,
)
from app.schemas.tia_proposal import (
    TiaActivateResponse,
    TiaSchemaApplyRequest,
    TiaSchemaApplyResponse,
    TiaSchemaPlanResponse,
    TiaSchemaRepairResponse,
    SchemaRegistryHint,
    TiaBatchApproveActivate,
    TiaBatchApproveActivateItem,
    TiaBatchApproveActivateResponse,
    TiaBatchActivate,
    TiaBatchActivateItem,
    TiaBatchActivateResponse,
    TiaBatchEnableBrowse,
    TiaBatchEnableBrowseError,
    TiaBatchEnableBrowseResponse,
    TiaBatchReview,
    TiaBatchReviewResponse,
    TiaPreflightTestResponse,
    TiaProposalMinPointsUpdate,
    TiaProposalPageResponse,
    TiaProposalResponse,
    TiaProposalReview,
    TiaProposalSummary,
)
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import TiaActivationService
from app.services.tia.proposal_service import TiaProposalService
from app.services.tia.scaffold_service import TiaScaffoldService
from app.services.tia.service import TIAService
from app.services.tia.scan.adapters.registry import list_scan_providers
from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions
from app.services.tia.scan.types import ScanOptions
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.preflight_test_service import TiaPreflightTestService
from app.services.tia.schema_maintenance_service import TiaSchemaMaintenanceService
from app.services.tia.schema_repair_service import TiaSchemaRepairService
from app.tasks.dispatch import dispatch_task
from app.tasks.tia_tasks import (
    run_tia_activate_task,
    run_tia_doc_pages_sync_task,
    run_tia_scan_task,
)

router = APIRouter()
_tia_service = TIAService()
_job_service = PlatformJobService()
_proposal_service = TiaProposalService()
_activation_service = TiaActivationService()
_scaffold_service = TiaScaffoldService()
_override_service = TiaOverrideService()
_schema_repair_service = TiaSchemaRepairService()
_schema_maintenance_service = TiaSchemaMaintenanceService()
_preflight_service = TiaPreflightTestService()


def _preflight_response(result) -> TiaPreflightTestResponse:
    return TiaPreflightTestResponse(**result.to_dict())


async def _save_preflight_on_proposal(session, proposal, result) -> None:
    steps = dict(proposal.activation_steps or {})
    steps["preflight_test"] = result.to_activation_step()
    proposal.activation_steps = steps
    await session.flush()


async def _run_preflight_sync(session, api_name: str, *, live_probe: bool = True):
    return await session.run_sync(
        lambda sync_sess: _preflight_service.run(sync_sess, api_name, live_probe=live_probe)
    )


@router.get(
    "/scan/providers",
    summary="可扫描的数据源列表",
    description="返回已实现 ProviderScanAdapter 的供应方 ID。",
)
async def list_scan_providers_endpoint(_: RequireAdmin) -> dict:
    return {"providers": list_scan_providers()}


@router.post(
    "/scan",
    response_model=TIAScanJobResponse,
    summary="TIA 变更扫描",
    description=(
        "对比 document/2 官方索引与本地 catalog，创建 platform_job 并异步更新进度(H-06)。"
        "默认 stock_a + document2 + probe_scope=all；积分门槛优先通过 live API 探测识别（迭代500，上限 500 接口）。"
    ),
)
async def scan_catalog(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
    body: TIAScanRequest = Body(default_factory=TIAScanRequest),
) -> TIAScanJobResponse:
    req = body
    options = ScanOptions(
        provider=req.provider,
        mode=req.mode,
        index_scope=req.index_scope,
        probe=req.probe,
        probe_scope=req.probe_scope,
        probe_limit=req.probe_limit,
        probe_unlimited=req.probe_unlimited,
        index_source=req.index_source,
        sync_doc_pages=(
            req.sync_doc_pages
            if req.sync_doc_pages is not None
            else False
        ),
        sync_doc_specs=(
            req.sync_doc_specs
            if req.sync_doc_specs is not None
            else req.mode == "full"
        ),
        sync_sdk_scan=(
            req.sync_sdk_scan
            if req.sync_sdk_scan is not None
            else req.mode == "full"
        ),
    )
    job_id = await _tia_service.start_scan(
        session, created_by_id=current_user.id, options=options
    )
    dispatch_task(run_tia_scan_task, job_id, options.to_dict())
    label = "全量" if options.mode == "full" else "快速"
    return TIAScanJobResponse(job_id=job_id, message=f"TIA {label} scan job queued")


@router.post(
    "/audit",
    response_model=TIAScanJobResponse,
    summary="积分审计",
    description="F-08 三源对照 stub：对比 catalog 与 overrides 缺口。",
)
async def audit_points(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> TIAScanJobResponse:
    job_id = await _tia_service.start_points_audit(session, created_by_id=current_user.id)
    return TIAScanJobResponse(job_id=job_id, message="Points audit complete")


@router.post(
    "/doc-pages/sync",
    response_model=TIAScanJobResponse,
    summary="官网接口页积分同步",
    description=(
        "按 document/2?doc_id=* 逐页抓取 api 与 min_points（Playwright 登录态），"
        "写入 doc_pages_cache、重建 api_by_doc_id、可选回写 sidebar 与 reconcile overrides。"
    ),
)
async def sync_doc_pages(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
    body: TiaDocPagesSyncRequest = Body(default_factory=TiaDocPagesSyncRequest),
) -> TIAScanJobResponse:
    opts = DocPagesSyncOptions(
        scope=body.scope,
        doc_ids=body.doc_ids,
        sleep_seconds=body.sleep_seconds,
        use_playwright=body.use_playwright,
        login_if_needed=body.login_if_needed,
        rebuild_registry=body.rebuild_registry,
        patch_sidebar=body.patch_sidebar,
        reconcile_overrides=body.reconcile_overrides,
        dry_run=body.dry_run,
    )
    job_id = await _tia_service.start_doc_pages_sync(
        session, created_by_id=current_user.id, options=opts
    )
    dispatch_task(run_tia_doc_pages_sync_task, job_id, opts.to_dict())
    label = "预览" if opts.dry_run else "同步"
    return TIAScanJobResponse(job_id=job_id, message=f"官网接口页积分{label}任务已提交")


@router.get(
    "/doc-auth",
    response_model=TiaDocAuthStatusResponse,
    summary="Tushare 文档站登录状态",
    description="查看 document/2 抓取所需的账号配置与会话 storage 状态（admin）。",
)
async def get_doc_auth_status(_: RequireAdmin) -> TiaDocAuthStatusResponse:
    from app.services.tia.tushare_doc_credential_service import get_doc_auth_status

    return TiaDocAuthStatusResponse(**get_doc_auth_status())


@router.put(
    "/doc-auth",
    response_model=TiaDocAuthStatusResponse,
    summary="保存 Tushare 文档站账号",
    description="将官网登录用户名/密码写入平台本地凭据文件（backend/data/，不入库）。",
)
async def save_doc_auth(
    _: RequireAdmin,
    body: TiaDocAuthUpdateRequest,
) -> TiaDocAuthStatusResponse:
    from app.services.tia.tushare_doc_credential_service import (
        get_doc_auth_status,
        save_doc_credentials,
    )

    try:
        save_doc_credentials(body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TiaDocAuthStatusResponse(**get_doc_auth_status())


@router.post(
    "/doc-auth/verify",
    response_model=TiaDocAuthVerifyResponse,
    summary="验证 Tushare 文档站登录",
    description=(
        "使用已保存凭据或 .env 通过 Playwright 登录 "
        "[document/2](https://tushare.pro/document/2)，并写入 storage 会话文件。"
    ),
)
def verify_doc_auth(_: RequireAdmin) -> TiaDocAuthVerifyResponse:
    """Sync route: Playwright uses sync API and must not run on the asyncio event loop."""
    from app.services.tia.tushare_doc_credential_service import verify_doc_login

    result = verify_doc_login()
    return TiaDocAuthVerifyResponse(**result)


@router.get(
    "/doc-points/coverage",
    response_model=TiaDocPointsCoverageResponse,
    summary="接口页积分覆盖审计",
    description=(
        "6 类检查：缺失 min_points、stale 缓存、解析失败、bundled 不一致、doc_id 冲突、"
        "doc_id 多接口（P0/P1 阻断）与 sidebar 漂移（P2 观测，iteration-20）。"
        "用于发现类似 top_inst 显示 — 或 doc_id 映射错误。"
    ),
)
async def doc_points_coverage(
    _: RequireAdmin,
) -> TiaDocPointsCoverageResponse:
    from app.services.tia.scan.doc_points_audit import run_doc_points_coverage_audit

    report = run_doc_points_coverage_audit()
    data = report.to_dict()
    return TiaDocPointsCoverageResponse(has_issues=report.has_issues, **data)


@router.get(
    "/scan/{job_id}",
    response_model=dict,
    summary="TIA 扫描进度",
    description="查询扫描 Job 进度与结果摘要。",
)
async def get_scan_job(
    job_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> dict:
    try:
        job = await _job_service.get(session, job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "result": job.result_json,
    }


@router.get(
    "/proposals/summary",
    response_model=TiaProposalSummary,
    summary="提案状态汇总",
    description="各状态提案数量统计。",
)
async def proposals_summary(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TiaProposalSummary:
    return await _proposal_service.status_summary(session)


@router.get(
    "/proposals/doc-link-audit",
    summary="提案文档链接对照",
    description="逐条对照提案 api_name 与 wctapi 文档页「接口：」名称是否一致。",
)
async def proposals_doc_link_audit(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> dict:
    from sqlalchemy import select

    from app.models.tia_proposal import TiaProposal
    from app.services.tia.proposal_doc_link_audit import audit_proposals
    from app.services.tia.proposal_enrichment import invalidate_api_meta_cache

    invalidate_api_meta_cache()
    rows = (await session.execute(select(TiaProposal).order_by(TiaProposal.id))).scalars().all()
    return audit_proposals(list(rows)).to_dict()


@router.get(
    "/proposals",
    response_model=TiaProposalPageResponse,
    summary="提案列表",
    description="分页、筛选、搜索 TIA 提案 (F-02)。",
)
async def list_proposals(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None, description="pending|approved|rejected|applied|failed"),
    q: str | None = Query(None, description="搜索 api_name / data_type / reason"),
    min_points_gte: int | None = Query(None, ge=0, description="最低积分（含）"),
    min_points_lte: int | None = Query(None, ge=0, description="最高积分（含）"),
    include_summary: bool = Query(True, description="是否返回全库状态汇总"),
) -> TiaProposalPageResponse:
    try:
        return await _proposal_service.list_proposals(
            session,
            skip=skip,
            limit=limit,
            status=status,
            q=q,
            min_points_gte=min_points_gte,
            min_points_lte=min_points_lte,
            include_summary=include_summary,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/proposals/{proposal_id}",
    response_model=TiaProposalResponse,
    summary="提案详情",
)
async def get_proposal(
    proposal_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TiaProposalResponse:
    try:
        return await _proposal_service.get_proposal_response(session, proposal_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.post(
    "/proposals/{proposal_id}/preflight-test",
    response_model=TiaPreflightTestResponse,
    summary="Preflight 测试（10 项）",
    description=(
        "审批/激活前运行：探针规格、采集模式、DDL、API 预算、实盘探针等。"
        "结果写入 proposal.activation_steps.preflight_test。"
    ),
)
async def run_proposal_preflight(
    proposal_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
    live_probe: bool = Query(True, description="是否执行 1 次实盘探针"),
) -> TiaPreflightTestResponse:
    try:
        proposal = await _proposal_service.get_proposal(session, proposal_id)
        if proposal.status == "rejected":
            raise ValidationError("已拒绝的提案不可测试")
        result = await _run_preflight_sync(session, proposal.api_name, live_probe=live_probe)
        await _save_preflight_on_proposal(session, proposal, result)
        await session.commit()
        return _preflight_response(result)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.patch(
    "/proposals/{proposal_id}",
    response_model=TiaProposalResponse,
    summary="审批提案",
    description="F-03 批准/拒绝；批准时写入 L1 tia_overrides。",
)
async def review_proposal(
    proposal_id: int,
    body: TiaProposalReview,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> TiaProposalResponse:
    try:
        result = await _proposal_service.review_proposal(
            session, proposal_id, body, approved_by_id=current_user.id
        )
        await session.commit()
        return result
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.patch(
    "/proposals/{proposal_id}/min-points",
    response_model=TiaProposalResponse,
    summary="修正提案积分",
    description=(
        "人工修正接口 min_points（pending 写入提案字段，不提前创建 L1 override）；"
        "批准后同步 tia_overrides；传 null 清除修正恢复文档值。"
    ),
)
async def update_proposal_min_points(
    proposal_id: int,
    body: TiaProposalMinPointsUpdate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TiaProposalResponse:
    try:
        result = await _proposal_service.update_min_points(session, proposal_id, body)
        await session.commit()
        return result
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post(
    "/proposals/batch-review",
    response_model=TiaBatchReviewResponse,
    summary="批量审批提案",
    description="批量批准/拒绝；可选 auto_activate 排队 L3。",
)
async def batch_review_proposals(
    body: TiaBatchReview,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> TiaBatchReviewResponse:
    review = TiaProposalReview(status=body.status, note=body.note, domain=body.domain)
    try:
        items, activate_pids = await _proposal_service.batch_review_proposals(
            session,
            body.proposal_ids,
            review,
            approved_by_id=current_user.id,
            auto_activate=body.auto_activate,
        )
        job_ids: list[int] = []
        if body.auto_activate and body.status == "approved":
            for pid in activate_pids:
                job_id = await _activation_service.start_activation(
                    session, pid, created_by_id=current_user.id
                )
                job_ids.append(job_id)
        await session.commit()
        for job_id in job_ids:
            dispatch_task(run_tia_activate_task, job_id)
        return TiaBatchReviewResponse(items=items, activate_job_ids=job_ids)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post(
    "/proposals/batch-approve-activate",
    response_model=TiaBatchApproveActivateResponse,
    summary="批量批准并激活",
    description="逐条批准（若待审）、Preflight 通过后排队 L3；失败项跳过并汇总。",
)
async def batch_approve_and_activate(
    body: TiaBatchApproveActivate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> TiaBatchApproveActivateResponse:
    items: list[TiaBatchApproveActivateItem] = []
    job_ids: list[int] = []
    succeeded = 0
    failed = 0
    for pid in body.proposal_ids:
        try:
            proposal = await _proposal_service.get_proposal(session, pid)
            if proposal.status == "pending":
                await _proposal_service.approve_and_get_id(
                    session,
                    pid,
                    current_user.id,
                    note=body.note,
                    domain=body.domain,
                )
                proposal = await _proposal_service.get_proposal(session, pid)
            elif proposal.status not in ("approved", "applied", "failed"):
                raise ValidationError(f"Cannot activate proposal in status {proposal.status}")
            if not body.skip_preflight:
                preflight = await _run_preflight_sync(
                    session, proposal.api_name, live_probe=True
                )
                await _save_preflight_on_proposal(session, proposal, preflight)
                if not preflight.passed:
                    raise ValidationError(
                        "Preflight 测试未通过: "
                        + "; ".join(preflight.blocking_errors or ["存在失败项"])
                    )
            job_id = await _activation_service.start_activation(
                session,
                pid,
                created_by_id=current_user.id,
            )
            job_ids.append(job_id)
            items.append(TiaBatchApproveActivateItem(proposal_id=pid, success=True, job_id=job_id))
            succeeded += 1
        except (NotFoundError, ValidationError) as exc:
            items.append(
                TiaBatchApproveActivateItem(proposal_id=pid, success=False, error=exc.message)
            )
            failed += 1
    await session.commit()
    for job_id in job_ids:
        dispatch_task(run_tia_activate_task, job_id)
    return TiaBatchApproveActivateResponse(
        items=items,
        job_ids=job_ids,
        succeeded=succeeded,
        failed=failed,
    )


@router.post(
    "/proposals/batch-activate",
    response_model=TiaBatchActivateResponse,
    summary="批量 L3 激活",
    description=(
        "对已批准/已激活/失败提案排队 L3 八步流水线（Celery 异步执行，HTTP 立即返回 job_ids）。"
        "不含 Preflight；待审提案请用 batch-approve-activate。"
    ),
)
async def batch_activate_proposals(
    body: TiaBatchActivate,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
) -> TiaBatchActivateResponse:
    items: list[TiaBatchActivateItem] = []
    job_ids: list[int] = []
    succeeded = 0
    failed = 0
    for pid in body.proposal_ids:
        try:
            proposal = await _proposal_service.get_proposal(session, pid)
            if proposal.status not in ("approved", "applied", "failed"):
                raise ValidationError(
                    f"Cannot L3-activate proposal in status {proposal.status}; approve first"
                )
            job_id = await _activation_service.start_activation(
                session,
                pid,
                created_by_id=current_user.id,
                reapply=body.reapply or proposal.status in ("applied", "failed"),
            )
            job_ids.append(job_id)
            items.append(TiaBatchActivateItem(proposal_id=pid, success=True, job_id=job_id))
            succeeded += 1
        except (NotFoundError, ValidationError) as exc:
            items.append(TiaBatchActivateItem(proposal_id=pid, success=False, error=exc.message))
            failed += 1
    await session.commit()
    for job_id in job_ids:
        dispatch_task(run_tia_activate_task, job_id)
    return TiaBatchActivateResponse(
        items=items,
        job_ids=job_ids,
        succeeded=succeeded,
        failed=failed,
    )


@router.post(
    "/proposals/batch-enable-browse",
    response_model=TiaBatchEnableBrowseResponse,
    summary="批量开通数据查询",
    description="对已激活（applied）提案批量启用 catalog 数据查询。",
)
async def batch_enable_proposal_browse(
    body: TiaBatchEnableBrowse,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TiaBatchEnableBrowseResponse:
    items, errors = await _proposal_service.batch_enable_browse(session, body.proposal_ids)
    await session.commit()
    refreshed = [
        await _proposal_service.get_proposal_response(session, r.id) for r in items
    ]
    return TiaBatchEnableBrowseResponse(
        items=refreshed,
        succeeded=len(refreshed),
        failed=len(errors),
        errors=[TiaBatchEnableBrowseError(**e) for e in errors],
    )


@router.post(
    "/proposals/{proposal_id}/approve-activate",
    response_model=TiaActivateResponse,
    summary="批准并激活",
    description="F-03 批准后先跑 Preflight，通过后排队 L3 八步流水线。",
)
async def approve_and_activate(
    proposal_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
    note: str | None = Query(None),
    domain: str | None = Query(None),
    reapply: bool = Query(False),
    force_schema: bool = Query(False, description="reapply 时强制重建 schema/DDL"),
    skip_preflight: bool = Query(False, description="跳过激活前 Preflight（不推荐）"),
) -> TiaActivateResponse:
    try:
        proposal = await _proposal_service.get_proposal(session, proposal_id)
        if proposal.status == "pending":
            await _proposal_service.approve_and_get_id(
                session, proposal_id, current_user.id, note=note, domain=domain
            )
            proposal = await _proposal_service.get_proposal(session, proposal_id)
        elif proposal.status not in ("approved", "applied", "failed"):
            raise ValidationError(f"Cannot activate proposal in status {proposal.status}")
        if not skip_preflight:
            preflight = await _run_preflight_sync(session, proposal.api_name, live_probe=True)
            await _save_preflight_on_proposal(session, proposal, preflight)
            if not preflight.passed:
                await session.commit()
                raise ValidationError(
                    "Preflight 测试未通过: "
                    + "; ".join(preflight.blocking_errors or ["存在失败项"])
                )
        job_id = await _activation_service.start_activation(
            session,
            proposal_id,
            created_by_id=current_user.id,
            reapply=reapply,
            force_schema=force_schema,
        )
        await session.commit()
        dispatch_task(run_tia_activate_task, job_id)
        return TiaActivateResponse(job_id=job_id, message="Approved and L3 activation queued")
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post(
    "/proposals/{proposal_id}/enable-browse",
    response_model=TiaProposalResponse,
    summary="启用数据查询",
    description="L3 已激活后，显式开启 catalog 数据查询（非默认）。",
)
async def enable_proposal_browse(
    proposal_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> TiaProposalResponse:
    try:
        proposal = await _proposal_service.get_proposal(session, proposal_id)
        if proposal.status != "applied":
            raise ValidationError("Proposal must be applied before enabling browse")
        await _override_service.enable_browse(session, proposal.api_name)
        await session.commit()
        return await _proposal_service.get_proposal_response(session, proposal_id)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/proposals/{proposal_id}/schema-plan",
    response_model=TiaSchemaPlanResponse,
    summary="Schema 运维预览",
    description="Dry-run：对比当前 override schema 与 catalog/registry 目标，返回 diff 与可用模式。",
)
async def get_proposal_schema_plan(
    proposal_id: int,
    async_session: Annotated[AsyncSession, Depends(get_async_session)],
    sync_session: Annotated[Session, Depends(get_sync_session)],
    _: RequireAdmin,
) -> TiaSchemaPlanResponse:
    try:
        proposal = await _proposal_service.get_proposal(async_session, proposal_id)
        if proposal.status not in ("applied", "failed", "approved"):
            raise ValidationError(
                f"Proposal {proposal_id} must be applied/approved/failed for schema maintenance"
            )
        result = _schema_maintenance_service.plan(sync_session, proposal.api_name)
        return TiaSchemaPlanResponse(**result)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.post(
    "/proposals/{proposal_id}/schema-apply",
    response_model=TiaSchemaApplyResponse,
    summary="Schema 运维应用",
    description="按 modes 应用列对齐或唯一键同步；删列/改键须 confirm_risk=true。",
)
async def apply_proposal_schema(
    proposal_id: int,
    body: TiaSchemaApplyRequest,
    async_session: Annotated[AsyncSession, Depends(get_async_session)],
    sync_session: Annotated[Session, Depends(get_sync_session)],
    _: RequireAdmin,
) -> TiaSchemaApplyResponse:
    try:
        proposal = await _proposal_service.get_proposal(async_session, proposal_id)
        if proposal.status not in ("applied", "failed", "approved"):
            raise ValidationError(
                f"Proposal {proposal_id} must be applied/approved/failed for schema maintenance"
            )
        result = _schema_maintenance_service.apply(
            sync_session,
            proposal.api_name,
            body.modes,
            confirm_risk=body.confirm_risk,
        )
        sync_session.commit()
        return TiaSchemaApplyResponse(**result)
    except (NotFoundError, ValidationError) as exc:
        sync_session.rollback()
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/schema-registry-hint",
    response_model=SchemaRegistryHint,
    summary="唯一键 registry 登记建议",
    description="返回建议在 unique_key_registry.py 中添加的代码片段（只读，不写入 override）。",
)
async def get_schema_registry_hint(
    _: RequireAdmin,
    api_name: str = Query(..., description="Tushare API 名称"),
) -> SchemaRegistryHint:
    return SchemaRegistryHint(**_schema_maintenance_service.registry_hint(api_name))


@router.post(
    "/proposals/{proposal_id}/repair-schema",
    response_model=TiaSchemaRepairResponse,
    summary="修复已激活 API 的 schema（兼容）",
    description=(
        "已废弃：请使用 schema-plan + schema-apply。"
        "内部按 drift 自动选择 modes 并 confirm_risk=true。"
    ),
    deprecated=True,
)
async def repair_proposal_schema(
    proposal_id: int,
    async_session: Annotated[AsyncSession, Depends(get_async_session)],
    sync_session: Annotated[Session, Depends(get_sync_session)],
    _: RequireAdmin,
) -> TiaSchemaRepairResponse:
    try:
        proposal = await _proposal_service.get_proposal(async_session, proposal_id)
        if proposal.status not in ("applied", "failed", "approved"):
            raise ValidationError(
                f"Proposal {proposal_id} must be applied/approved before schema repair"
            )
        result = _schema_repair_service.repair_api_sync(sync_session, proposal.api_name)
        sync_session.commit()
        return TiaSchemaRepairResponse(**result)
    except (NotFoundError, ValidationError) as exc:
        sync_session.rollback()
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get(
    "/proposals/{proposal_id}/scaffold",
    summary="L2 脚手架下载",
    description="F-05 返回 scaffold zip 包。",
)
async def download_scaffold(
    proposal_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    _: RequireAdmin,
) -> Response:
    proposal = await _proposal_service.get_proposal(session, proposal_id)
    if proposal.status not in ("approved", "applied"):
        raise HTTPException(status_code=400, detail="Proposal must be approved")
    try:
        override = await _override_service.get_by_api(session, proposal.api_name)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    content = _scaffold_service.build_zip(override)
    filename = f"tia_scaffold_{proposal.api_name}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/proposals/{proposal_id}/activate",
    response_model=TiaActivateResponse,
    summary="L3 激活",
    description="F-06 注册 catalog/handler/sync_task；F-07 reapply 用 query reapply=true。",
)
async def activate_proposal(
    proposal_id: int,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    current_user: RequireAdmin,
    reapply: bool = Query(False),
    force_schema: bool = Query(
        False,
        description="reapply 时强制重建 schema/DDL/handler/任务 Cron（修复 cal_date 等列名问题）",
    ),
) -> TiaActivateResponse:
    try:
        job_id = await _activation_service.start_activation(
            session,
            proposal_id,
            created_by_id=current_user.id,
            reapply=reapply,
            force_schema=force_schema,
        )
        await session.commit()
        dispatch_task(run_tia_activate_task, job_id)
        return TiaActivateResponse(job_id=job_id, message="L3 activation queued")
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
