"""Workflow API and engine tests."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.models.workflow import NodeRun, Workflow, WorkflowEdge, WorkflowNode, WorkflowRun
from app.services.workflow.dag import DagEngine
from app.services.workflow.nodes.registry import ALLOWED_NODE_TYPES
from app.services.workflow.validator import WorkflowValidator
from catalog_test_support import TEST_DATA_TYPE


async def _seed_graph(db_session, *, status: str = "draft", with_source: bool = True) -> Workflow:
    workflow = Workflow(name="测试工作流", status=status, description="test")
    db_session.add(workflow)
    await db_session.flush()
    db_session.add_all(
        [
            WorkflowNode(
                workflow_id=workflow.id,
                node_id="gate-1",
                node_type="gate",
                label="交易日",
                position_x=80,
                position_y=120,
            ),
            WorkflowNode(
                workflow_id=workflow.id,
                node_id="collect-1",
                node_type="collect",
                label="日线采集",
                position_x=280,
                position_y=120,
                data_type=TEST_DATA_TYPE,
                source_id=1 if with_source else None,
            ),
        ]
    )
    db_session.add(
        WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="gate-1",
            target_node_id="collect-1",
        )
    )
    await db_session.flush()
    return workflow


@pytest.mark.asyncio
async def test_workflow_runs_and_nodes(client: AsyncClient, db_session) -> None:
    workflow = Workflow(name="收盘同步", status="published", description="test")
    db_session.add(workflow)
    await db_session.flush()

    run = WorkflowRun(
        workflow_id=workflow.id,
        status="success",
        trigger_type="manual",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add_all(
        [
            NodeRun(
                workflow_run_id=run.id,
                node_id="gate-1",
                node_type="gate",
                label="交易日",
                status="success",
            ),
            NodeRun(
                workflow_run_id=run.id,
                node_id="collect-1",
                node_type="collect",
                label="日线采集",
                status="success",
                message="ok",
                result_json={
                    "batch_mode": "daily",
                    "collect_start_date": "2026-06-10",
                    "collect_end_date": "2026-06-10",
                    "stock_code_offset": 200,
                    "api_calls": 1,
                },
            ),
        ]
    )
    await db_session.commit()

    runs_resp = await client.get(f"/api/v1/workflows/{workflow.id}/runs")
    assert runs_resp.status_code == 200
    runs_data = runs_resp.json()
    assert runs_data["total"] == 1
    assert runs_data["items"][0]["workflow_name"] == "收盘同步"

    nodes_resp = await client.get(f"/api/v1/workflows/runs/{run.id}/nodes")
    assert nodes_resp.status_code == 200
    nodes_data = nodes_resp.json()
    assert nodes_data["total"] == 2
    assert {n["node_type"] for n in nodes_data["items"]} == {"gate", "collect"}
    collect_node = next(n for n in nodes_data["items"] if n["node_type"] == "collect")
    assert collect_node["result_json"]["batch_mode"] == "daily"
    assert collect_node["result_json"]["stock_code_offset"] == 200


@pytest.mark.asyncio
async def test_workflow_collect_profile(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/workflows/collect-profile",
        params={"data_type": TEST_DATA_TYPE, "batch_mode": "daily"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_name"] == "income"
    assert data["collect_mode"] == "period"
    assert data["max_codes_effective"] == 100
    assert data["recent_periods"] == 2


@pytest.mark.asyncio
async def test_workflow_run_backfill_trigger(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="published")
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/workflows/{workflow.id}/run?batch_mode=backfill&async_queue=false"
    )
    assert resp.status_code == 200
    run = await db_session.get(WorkflowRun, resp.json()["run_id"])
    assert run is not None
    assert run.trigger_type == "backfill"


@pytest.mark.asyncio
async def test_workflow_run_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/runs/9999/nodes")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_workflow_runs_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows/9999/runs")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_workflow_debug_run_skip_gates(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="draft")
    await db_session.commit()

    resp = await client.post(f"/api/v1/workflows/{workflow.id}/run?skip_gates=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"

    nodes_resp = await client.get(f"/api/v1/workflows/runs/{data['run_id']}/nodes")
    statuses = {n["node_id"]: n["status"] for n in nodes_resp.json()["items"]}
    assert statuses["gate-1"] == "skipped"
    assert statuses["collect-1"] == "success"


@pytest.mark.asyncio
async def test_workflow_publish_requires_source(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="draft", with_source=False)
    await db_session.commit()

    resp = await client.post(f"/api/v1/workflows/{workflow.id}/publish")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_workflow_publish_success(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="draft", with_source=True)
    await db_session.commit()

    resp = await client.post(f"/api/v1/workflows/{workflow.id}/publish")
    assert resp.status_code == 200
    assert "已发布" in resp.json()["message"]

    graph_resp = await client.get(f"/api/v1/workflows/{workflow.id}/graph")
    assert graph_resp.json()["status"] == "published"


@pytest.mark.asyncio
async def test_workflow_clone(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="published")
    await db_session.commit()

    resp = await client.post(f"/api/v1/workflows/{workflow.id}/clone")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_id"] != workflow.id
    assert "副本" in data["name"]

    graph_resp = await client.get(f"/api/v1/workflows/{data['workflow_id']}/graph")
    graph = graph_resp.json()
    assert graph["status"] == "draft"
    assert len(graph["nodes"]) == 2


def test_validator_detects_cycle() -> None:
    validator = WorkflowValidator()
    nodes = [
        WorkflowNode(workflow_id=1, node_id="a", node_type="gate"),
        WorkflowNode(workflow_id=1, node_id="b", node_type="collect", data_type=TEST_DATA_TYPE),
    ]
    edges = [
        WorkflowEdge(workflow_id=1, source_node_id="a", target_node_id="b"),
        WorkflowEdge(workflow_id=1, source_node_id="b", target_node_id="a"),
    ]
    errors = validator.collect_errors(nodes, edges)
    assert any("环" in e for e in errors)


@pytest.mark.asyncio
async def test_workflow_save_graph(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="draft")
    await db_session.commit()

    payload = {
        "nodes": [
            {
                "node_id": "gate-1",
                "node_type": "gate",
                "label": "交易日",
                "position_x": 100,
                "position_y": 100,
            },
            {
                "node_id": "collect-1",
                "node_type": "collect",
                "label": "日线",
                "position_x": 300,
                "position_y": 100,
                "data_type": TEST_DATA_TYPE,
                "source_id": 1,
            },
        ],
        "edges": [{"source_node_id": "gate-1", "target_node_id": "collect-1"}],
    }
    resp = await client.put(f"/api/v1/workflows/{workflow.id}/graph", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["position_x"] == 100


def test_trading_calendar_weekend() -> None:
    from datetime import date

    from app.services.trading_calendar.service import TradingCalendarService

    svc = TradingCalendarService()
    ok, msg = svc.is_trading_day(date(2025, 6, 14))  # Saturday
    assert ok is False
    assert "周末" in msg


def test_cron_matches_weekday() -> None:
    from datetime import datetime, timezone, timedelta

    from app.services.workflow.scheduler import cron_matches

    sh = timezone(timedelta(hours=8))
    dt = datetime(2025, 6, 13, 16, 0, tzinfo=sh)  # Fri 16:00
    assert cron_matches("0 16 * * 1-5", dt) is True


def test_allowed_node_types_include_quality() -> None:
    assert "quality" in ALLOWED_NODE_TYPES
    assert "gate" in ALLOWED_NODE_TYPES
    assert "collect" in ALLOWED_NODE_TYPES


def test_dag_downstream_skip() -> None:
    engine = DagEngine()
    nodes = [
        WorkflowNode(workflow_id=1, node_id="a", node_type="gate"),
        WorkflowNode(workflow_id=1, node_id="b", node_type="collect"),
        WorkflowNode(workflow_id=1, node_id="c", node_type="collect"),
    ]
    edges = [
        WorkflowEdge(workflow_id=1, source_node_id="a", target_node_id="b"),
        WorkflowEdge(workflow_id=1, source_node_id="b", target_node_id="c"),
    ]
    plan = engine.build_plan(nodes, edges)
    downstream = engine.downstream_of(plan, "a")
    assert downstream == {"b", "c"}


@pytest.mark.asyncio
async def test_workflow_create_and_delete(client: AsyncClient) -> None:
    create = await client.post("/api/v1/workflows", json={"name": "临时工作流"})
    assert create.status_code == 200
    wf_id = create.json()["workflow_id"]

    validate = await client.get(f"/api/v1/workflows/{wf_id}/validate")
    assert validate.status_code == 200
    assert validate.json()["valid"] is False

    delete = await client.delete(f"/api/v1/workflows/{wf_id}")
    assert delete.status_code == 200


@pytest.mark.asyncio
async def test_workflow_unpublish(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="published")
    await db_session.commit()

    resp = await client.post(f"/api/v1/workflows/{workflow.id}/unpublish")
    assert resp.status_code == 200
    graph = await client.get(f"/api/v1/workflows/{workflow.id}/graph")
    assert graph.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_workflow_validate_for_publish(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="draft", with_source=True)
    await db_session.commit()

    resp = await client.get(f"/api/v1/workflows/{workflow.id}/validate?for_publish=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_workflow_collect_failure_returns_failed_not_500(
    client: AsyncClient, db_session
) -> None:
    from unittest.mock import MagicMock, patch

    from app.services.workflow.nodes.base import NodeResult

    workflow = await _seed_graph(db_session, status="published")
    await db_session.commit()

    def _mock_execute(_session, node, *, skip_gates=False, context=None):
        if node.node_type == "gate":
            from app.services.workflow.nodes.base import NodeResult

            if skip_gates:
                return NodeResult(status="skipped", message="调试跳过")
            return NodeResult(status="success", message="ok")
        return NodeResult(status="failed", message="采集模拟失败")

    mock_handler = MagicMock()
    mock_handler.execute.side_effect = _mock_execute

    with patch("app.services.workflow.executor.get_node_handler", return_value=mock_handler):
        resp = await client.post(f"/api/v1/workflows/{workflow.id}/run?skip_gates=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"

    nodes_resp = await client.get(f"/api/v1/workflows/runs/{data['run_id']}/nodes")
    statuses = {n["node_id"]: n["status"] for n in nodes_resp.json()["items"]}
    assert statuses["collect-1"] == "failed"


@pytest.mark.asyncio
async def test_workflow_trigger_run_async_default(client: AsyncClient, db_session) -> None:
    from unittest.mock import patch

    workflow = await _seed_graph(db_session, status="published")
    await db_session.commit()

    with patch("app.services.workflow.service.WorkflowService._enqueue_workflow_run") as enqueue:
        resp = await client.post(f"/api/v1/workflows/{workflow.id}/run")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "队列" in data["message"]
    enqueue.assert_called_once()
    assert enqueue.call_args.args[0] == data["run_id"]


@pytest.mark.asyncio
async def test_workflow_trigger_run_sync_queue(client: AsyncClient, db_session) -> None:
    workflow = await _seed_graph(db_session, status="published")
    await db_session.commit()

    resp = await client.post(f"/api/v1/workflows/{workflow.id}/run?async_queue=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"

    nodes_resp = await client.get(f"/api/v1/workflows/runs/{data['run_id']}/nodes")
    statuses = {n["node_id"]: n["status"] for n in nodes_resp.json()["items"]}
    assert statuses["gate-1"] == "success"
    assert statuses["collect-1"] == "success"


def test_trigger_run_sync_enqueues() -> None:
    from unittest.mock import patch

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.base import Base
    from app.models.platform_job import PlatformJob  # noqa: F401
    from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode
    from app.services.workflow.service import WorkflowService
    from catalog_test_support import TEST_DATA_TYPE

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    workflow = Workflow(name="cron wf", status="published", schedule_cron="0 18 * * 1-5")
    session.add(workflow)
    session.flush()
    session.add_all(
        [
            WorkflowNode(
                workflow_id=workflow.id,
                node_id="gate-1",
                node_type="gate",
                label="交易日",
                position_x=0,
                position_y=0,
            ),
            WorkflowNode(
                workflow_id=workflow.id,
                node_id="collect-1",
                node_type="collect",
                label="采集",
                position_x=100,
                position_y=0,
                data_type=TEST_DATA_TYPE,
                source_id=1,
            ),
        ]
    )
    session.add(
        WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id="gate-1",
            target_node_id="collect-1",
        )
    )
    session.commit()

    service = WorkflowService()
    with patch.object(WorkflowService, "_enqueue_workflow_run") as enqueue:
        result = service.trigger_run_sync(session, workflow.id, trigger_type="cron")
    assert result.status == "pending"
    assert "队列" in result.message
    enqueue.assert_called_once()
    session.close()


@pytest.mark.asyncio
async def test_workflow_quality_node_validation(client: AsyncClient, db_session) -> None:
    workflow = Workflow(name="质检流", status="draft")
    db_session.add(workflow)
    await db_session.flush()
    db_session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id="q1",
            node_type="quality",
            label="质检",
            data_type=TEST_DATA_TYPE,
        )
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/workflows/{workflow.id}/validate?for_publish=true")
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
