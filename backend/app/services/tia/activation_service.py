"""TIA L3 activation pipeline (F-06/F-07) — eight-step orchestration."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.platform_job import PlatformJob
from app.models.sync_task import SyncTask
from app.models.tia_proposal import TiaProposal
from app.services.catalog.canonical_standard import (
    resolve_schema_for_ddl,
    validate_canonical_for_ddl,
)
from app.services.catalog.field_resolution import live_fields_from_activation_steps
from app.services.platform.job_service import PlatformJobService
from app.services.tia.credentials import resolve_tushare_collect_credentials
from app.services.tia.constants import api_to_data_type, api_to_table_name, data_type_aliases
from app.services.tia.migration_service import TiaMigrationService
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.quality_setup_service import TiaQualitySetupService
from app.services.tia.schema_inference import (
    schema_to_catalog_columns,
    schema_to_catalog_filters,
)
from app.services.tia.collect_pattern import enrich_schema_collect, validate_collect_pattern
from app.services.tia.preflight_test_service import TiaPreflightTestService
from app.services.tia.unique_key_registry import enrich_schema_keys
from app.services.tia.sync_profiles import SyncProfile, resolve_sync_profile
from app.sync.tia_handler import register_tia_handler

ACTIVATION_STEPS = (
    "preflight_test",
    "infer_schema",
    "run_migration",
    "register_catalog",
    "register_handler",
    "create_sync_task",
    "setup_quality",
    "trigger_initial_collect",
)


class TiaActivationService:
    def __init__(self) -> None:
        self._jobs = PlatformJobService()
        self._overrides = TiaOverrideService()
        self._migration = TiaMigrationService()
        self._quality = TiaQualitySetupService()

    @staticmethod
    def _apply_sync_profile(
        task: SyncTask,
        profile: SyncProfile,
        *,
        force_update_cron: bool = False,
    ) -> None:
        if profile.schedule_cron and (force_update_cron or not task.schedule_cron):
            task.schedule_cron = profile.schedule_cron
        if profile.auto_activate and task.status == "paused":
            task.status = "active"

    @staticmethod
    def _apply_data_source(task: SyncTask, session: Session) -> None:
        if task.source_id is not None:
            return
        from app.services.tia.credentials_tdx import resolve_collect_source_credentials

        creds = resolve_collect_source_credentials(session, None, data_type=task.data_type)
        source_id = creds.get("source_id")
        if source_id is not None:
            task.source_id = int(source_id)

    def _ensure_sync_task_sync(
        self,
        session: Session,
        *,
        data_type: str,
        api_name: str,
        profile: SyncProfile,
    ) -> tuple[SyncTask, bool]:
        existing = session.execute(
            select(SyncTask).where(SyncTask.data_type == data_type)
        ).scalar_one_or_none()
        if existing is not None:
            self._apply_sync_profile(existing, profile)
            self._link_upstream_task(session, existing, api_name)
            self._apply_data_source(existing, session)
            session.flush()
            return existing, False
        task = SyncTask(
            name=f"TIA:{api_name}",
            data_type=data_type,
            status="active" if profile.auto_activate else "paused",
            schedule_cron=profile.schedule_cron,
        )
        self._link_upstream_task(session, task, api_name)
        self._apply_data_source(task, session)
        session.add(task)
        session.flush()
        return task, True

    @staticmethod
    def _link_upstream_task(session: Session, task: SyncTask, api_name: str) -> None:
        if api_name != "daily" or task.upstream_task_id is not None:
            return
        upstream = session.execute(
            select(SyncTask).where(SyncTask.data_type == api_to_data_type("stock_basic"))
        ).scalar_one_or_none()
        if upstream is not None:
            task.upstream_task_id = upstream.id

    async def start_activation(
        self,
        session,
        proposal_id: int,
        created_by_id: int | None,
        reapply: bool = False,
        force_schema: bool = False,
    ) -> int:
        proposal = await session.get(TiaProposal, proposal_id)
        if proposal is None:
            raise NotFoundError(f"Proposal {proposal_id} not found")
        if proposal.status not in ("approved", "applied", "failed") and not reapply:
            raise ValidationError("Proposal must be approved before activation")
        job = await self._jobs.create(
            session,
            "tia_activate",
            created_by_id=created_by_id,
        )
        job.result_json = {
            "proposal_id": proposal_id,
            "reapply": reapply,
            "force_schema": force_schema,
        }
        await session.flush()
        return job.id

    def execute_activation_sync(self, session: Session, job_id: int) -> dict[str, Any]:
        job = session.get(PlatformJob, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        params = job.result_json or {}
        proposal_id = params.get("proposal_id")
        reapply = bool(params.get("reapply"))
        force_schema = bool(params.get("force_schema"))
        proposal = session.get(TiaProposal, proposal_id)
        if proposal is None:
            raise NotFoundError(f"Proposal {proposal_id} not found")

        steps: dict[str, Any] = dict(proposal.activation_steps or {})
        self._jobs.update_sync(
            session,
            job_id,
            status="running",
            progress=5,
            message=f"Activating {proposal.api_name}",
        )
        session.commit()

        try:
            override = self._overrides.get_by_api_sync(session, proposal.api_name)
        except NotFoundError:
            override = self._overrides.build_override_from_api(proposal.api_name)
            session.add(override)
            session.flush()

        data_type = proposal.data_type or override.data_type or api_to_data_type(proposal.api_name)
        if data_type.startswith("tdx_"):
            data_type = api_to_data_type(proposal.api_name, provider="tdx")
        proposal.data_type = data_type
        table_name = override.table_name or api_to_table_name(proposal.api_name, provider="tdx" if data_type.startswith("tdx_") else "tushare")
        override.table_name = table_name

        schema: dict[str, Any] = {}
        sync_profile = resolve_sync_profile(proposal.api_name)
        sync_task_id: int | None = None

        for idx, step in enumerate(ACTIVATION_STEPS):
            skip_on_reapply = (
                reapply
                and steps.get(step, {}).get("status") == "success"
                and not (
                    force_schema
                    and step
                    in ("infer_schema", "run_migration", "register_handler", "create_sync_task")
                )
            )
            if skip_on_reapply:
                if step == "create_sync_task":
                    schema = (override.override_json or {}).get("schema") or schema
                    profile = resolve_sync_profile(proposal.api_name, schema)
                    task, _ = self._ensure_sync_task_sync(
                        session,
                        data_type=data_type,
                        api_name=proposal.api_name,
                        profile=profile,
                    )
                    sync_task_id = task.id
                if step == "infer_schema":
                    schema = (override.override_json or {}).get("schema") or schema
                if step == "preflight_test":
                    pass
                continue
            progress = 10 + int((idx + 1) / len(ACTIVATION_STEPS) * 85)
            try:
                if step == "preflight_test":
                    preflight = TiaPreflightTestService().run(
                        session,
                        proposal.api_name,
                        live_probe=True,
                    )
                    steps[step] = preflight.to_activation_step()
                    if not preflight.passed:
                        raise ValidationError(
                            "Preflight 测试未通过: "
                            + "; ".join(preflight.blocking_errors or ["存在失败项"])
                        )
                elif step == "infer_schema":
                    existing = (override.override_json or {}).get("schema")
                    live_fields = live_fields_from_activation_steps(steps)
                    if not live_fields:
                        raise ValidationError(
                            "infer_schema 需要 Preflight 实盘探针 actual_fields；"
                            "请配置 Tushare Token 并确保探针成功"
                        )
                    schema = resolve_schema_for_ddl(
                        proposal.api_name,
                        existing,
                        force_rebuild=True,
                        live_fields=live_fields,
                        require_live_actual=True,
                    )
                    pattern_validation = validate_collect_pattern(proposal.api_name)
                    if pattern_validation.blocking_errors:
                        raise ValidationError(
                            "采集模式校验未通过: " + "; ".join(pattern_validation.blocking_errors)
                        )
                    schema = enrich_schema_collect(schema, proposal.api_name)
                    schema = enrich_schema_keys(schema, proposal.api_name, table_name=table_name)
                    ddl_errors = validate_canonical_for_ddl(schema, proposal.api_name)
                    if ddl_errors:
                        raise ValidationError(
                            f"Data standard not ready for DDL: {'; '.join(ddl_errors)}"
                        )
                    profile = resolve_sync_profile(proposal.api_name, schema)
                    sync_profile = profile
                    oj = dict(override.override_json or {})
                    oj["schema"] = schema
                    override.override_json = oj
                    cp = schema.get("collect_pattern") or {}
                    steps[step] = {
                        "status": "success",
                        "columns": len(schema.get("columns", [])),
                        "ddl_ready": True,
                        "unique_keys": schema.get("unique_keys") or [],
                        "indexes": schema.get("indexes") or [],
                        "unique_constraint": schema.get("unique_constraint"),
                        "collect_pattern": cp.get("pattern"),
                        "collect_mode": cp.get("mode"),
                        "pattern_mismatch": cp.get("pattern_mismatch"),
                        "live_field_count": len(live_fields or []),
                    }
                elif step == "run_migration":
                    if not schema:
                        existing = (override.override_json or {}).get("schema")
                        schema = resolve_schema_for_ddl(proposal.api_name, existing)
                    ddl_errors = validate_canonical_for_ddl(schema, proposal.api_name)
                    if ddl_errors:
                        raise ValidationError(
                            f"Refusing run_migration: {'; '.join(ddl_errors)}"
                        )
                    created = self._migration.ensure_table(session, table_name, schema)
                    synced = self._migration.sync_table_schema(session, table_name, schema)
                    steps[step] = {
                        "status": "success",
                        "table_created": created,
                        "columns_added": synced.get("columns_added") or [],
                        "columns_dropped": synced.get("columns_dropped") or [],
                        "unique_index_created": bool(synced.get("unique_index_created")),
                        "browse_indexes_created": synced.get("browse_indexes_created") or [],
                        "unique_keys": schema.get("unique_keys") or [],
                    }
                elif step == "register_catalog":
                    if not schema:
                        schema = (override.override_json or {}).get("schema") or {}
                    override.is_activated = True
                    self._overrides.apply_to_registry(
                        override,
                        columns=schema_to_catalog_columns(schema),
                        filters=schema_to_catalog_filters(schema),
                        browse_enabled=False,
                    )
                    steps[step] = {"status": "success"}
                elif step == "register_handler":
                    if not schema:
                        schema = (override.override_json or {}).get("schema") or {}
                    register_tia_handler(proposal.api_name, data_type, schema)
                    steps[step] = {"status": "success"}
                elif step == "create_sync_task":
                    if not schema:
                        schema = (override.override_json or {}).get("schema") or {}
                    profile = resolve_sync_profile(proposal.api_name, schema)
                    sync_profile = profile
                    task, created = self._ensure_sync_task_sync(
                        session,
                        data_type=data_type,
                        api_name=proposal.api_name,
                        profile=sync_profile,
                    )
                    if force_schema and not created:
                        self._apply_sync_profile(task, sync_profile, force_update_cron=True)
                        session.flush()
                    sync_task_id = task.id
                    steps[step] = {
                        "status": "success",
                        "task_id": task.id,
                        "created": created,
                        "sync_mode": sync_profile.mode,
                        "schedule_cron": task.schedule_cron,
                        "task_status": task.status,
                    }
                elif step == "setup_quality":
                    if not schema:
                        schema = (override.override_json or {}).get("schema") or {}
                    rules_created = self._quality.setup_default_rules(session, data_type, schema)
                    steps[step] = {"status": "success", "rules_created": rules_created}
                elif step == "trigger_initial_collect":
                    if not sync_profile.trigger_initial:
                        steps[step] = {
                            "status": "skipped",
                            "reason": f"sync_mode={sync_profile.mode}",
                        }
                    else:
                        if sync_task_id is None:
                            task = session.execute(
                                select(SyncTask).where(SyncTask.data_type == data_type)
                            ).scalar_one_or_none()
                            if task is None:
                                raise ValidationError(
                                    f"No sync_task for {data_type}; create_sync_task must run first"
                                )
                            sync_task_id = task.id
                        from app.tasks.dispatch import dispatch_task
                        from app.tasks.sync_tasks import run_collect

                        dispatch_task(run_collect, sync_task_id)
                        steps[step] = {
                            "status": "success",
                            "task_id": sync_task_id,
                            "message": "Initial collect queued",
                            "sync_mode": sync_profile.mode,
                        }
                proposal.activation_steps = steps
                self._jobs.update_sync(
                    session,
                    job_id,
                    progress=progress,
                    message=f"Step {step} done",
                )
                session.commit()
            except Exception as exc:
                if step == "preflight_test" and "preflight" in locals():
                    step_meta = preflight.to_activation_step()
                    step_meta["error"] = str(exc)
                    steps[step] = step_meta
                else:
                    steps[step] = {"status": "failed", "error": str(exc)}
                proposal.status = "failed"
                proposal.activation_steps = steps
                self._jobs.update_sync(
                    session,
                    job_id,
                    status="failed",
                    error=str(exc),
                    message=f"Step {step} failed",
                    result_json={"steps": steps},
                )
                session.commit()
                raise

        proposal.status = "applied"
        override.is_activated = True
        self._jobs.update_sync(
            session,
            job_id,
            status="success",
            progress=100,
            message=f"L3 activation complete for {data_type}",
            result_json={"data_type": data_type, "table_name": table_name, "steps": steps},
        )
        session.commit()
        return {"data_type": data_type, "table_name": table_name, "steps": steps}
