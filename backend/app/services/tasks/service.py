"""Sync task business logic."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.core.exceptions import NotFoundError, ValidationError
from app.models.data_source import DataSource
from app.models.sync_task import SyncTask
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal
from app.schemas.task import SyncTaskCreate, SyncTaskPageResponse, SyncTaskResponse, SyncTaskUpdate
from app.services.tasks.collect_config_service import (
    CollectConfigService,
    validate_task_collect_params_for_api,
    _schema_for_data_type_async,
)


class TaskService:
    def __init__(self) -> None:
        self._collect_config = CollectConfigService()

    async def _validated_collect_params(
        self,
        session: AsyncSession,
        data_type: str,
        raw: dict | None,
    ) -> dict | None:
        api_name, schema = await _schema_for_data_type_async(session, data_type)
        return validate_task_collect_params_for_api(api_name, schema, raw)

    async def _resolve_tia_link(
        self,
        session: AsyncSession,
        data_type: str,
    ) -> tuple[str | None, int | None]:
        override = (
            await session.execute(select(TiaOverride).where(TiaOverride.data_type == data_type))
        ).scalar_one_or_none()
        if override is None:
            return None, None
        proposal_id = (
            await session.execute(
                select(TiaProposal.id)
                .where(TiaProposal.api_name == override.api_name)
                .order_by(TiaProposal.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return override.api_name, proposal_id

    async def _source_name(self, session: AsyncSession, source_id: int | None) -> str | None:
        if source_id is None:
            return None
        source = await session.get(DataSource, source_id)
        return source.name if source else None

    async def _to_response(self, session: AsyncSession, task: SyncTask) -> SyncTaskResponse:
        entry = get_data_type_entry(task.data_type)
        label = entry.label if entry else task.data_type
        tia_api_name, proposal_id = await self._resolve_tia_link(session, task.data_type)
        source_name = await self._source_name(session, task.source_id)
        return SyncTaskResponse(
            id=task.id,
            name=task.name,
            source_id=task.source_id,
            data_type=task.data_type,
            data_type_label=label,
            schedule_cron=task.schedule_cron,
            status=task.status,
            upstream_task_id=task.upstream_task_id,
            next_run_at=task.next_run_at,
            tia_api_name=tia_api_name,
            proposal_id=proposal_id,
            source_name=source_name,
            collect_params=task.collect_params,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    def _validate_data_type(self, data_type: str) -> None:
        if get_data_type_entry(data_type) is None:
            raise ValidationError(
                f"Unknown data_type '{data_type}'; must exist in catalog registry",
                details={"data_type": data_type},
            )

    async def list_tasks(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> SyncTaskPageResponse:
        query = select(SyncTask)
        if status:
            query = query.where(SyncTask.status == status)
        count_query = select(func.count()).select_from(SyncTask)
        if status:
            count_query = count_query.where(SyncTask.status == status)
        total = (await session.execute(count_query)).scalar_one()
        result = await session.execute(
            query.order_by(SyncTask.id.desc()).offset(skip).limit(limit)
        )
        tasks = result.scalars().all()
        page = (skip // limit) + 1 if limit else 1
        return SyncTaskPageResponse(
            items=[await self._to_response(session, t) for t in tasks],
            total=total,
            page=page,
            size=limit,
        )

    async def create_task(self, session: AsyncSession, body: SyncTaskCreate) -> SyncTaskResponse:
        self._validate_data_type(body.data_type)
        if body.upstream_task_id is not None:
            upstream = await session.get(SyncTask, body.upstream_task_id)
            if upstream is None:
                raise NotFoundError(f"Upstream task {body.upstream_task_id} not found")
        task = SyncTask(
            name=body.name,
            source_id=body.source_id,
            data_type=body.data_type,
            schedule_cron=body.schedule_cron,
            status=body.status,
            upstream_task_id=body.upstream_task_id,
            collect_params=await self._validated_collect_params(
                session, body.data_type, body.collect_params
            ),
        )
        session.add(task)
        await session.flush()
        await session.refresh(task)
        return await self._to_response(session, task)

    async def update_task(
        self,
        session: AsyncSession,
        task_id: int,
        body: SyncTaskUpdate,
    ) -> SyncTaskResponse:
        task = await session.get(SyncTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        if body.data_type is not None:
            self._validate_data_type(body.data_type)
            task.data_type = body.data_type
        if body.name is not None:
            task.name = body.name
        if body.source_id is not None:
            task.source_id = body.source_id
        if body.schedule_cron is not None:
            task.schedule_cron = body.schedule_cron
        if body.status is not None:
            task.status = body.status
        if body.upstream_task_id is not None:
            upstream = await session.get(SyncTask, body.upstream_task_id)
            if upstream is None:
                raise NotFoundError(f"Upstream task {body.upstream_task_id} not found")
            task.upstream_task_id = body.upstream_task_id
        if "collect_params" in body.model_fields_set:
            data_type = body.data_type or task.data_type
            task.collect_params = await self._validated_collect_params(
                session, data_type, body.collect_params
            )
        await session.flush()
        await session.refresh(task)
        return await self._to_response(session, task)

    async def get_task(self, session: AsyncSession, task_id: int) -> SyncTaskResponse:
        task = await session.get(SyncTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        return await self._to_response(session, task)
