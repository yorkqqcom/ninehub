"""Tests for setup_collect_workflows preflight helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_collect_workflows.py"
_spec = importlib.util.spec_from_file_location("setup_collect_workflows_testmod", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


def test_workflow_apis_match_daily_batch_overrides() -> None:
    assert len(_mod.WORKFLOW_APIS) == len(_mod.DAILY_BATCH_MODE_OVERRIDES)
    assert set(_mod.WORKFLOW_APIS) == set(_mod.DAILY_BATCH_MODE_OVERRIDES.keys())


def test_min_account_points_default_2000() -> None:
    assert _mod.MIN_ACCOUNT_POINTS == 2000


def test_load_script_module_registers_sys_modules_for_dataclasses() -> None:
    mod = _mod._load_script_module("run_backfill_history.py")
    assert hasattr(mod, "list_plan")
    assert hasattr(mod, "ChunkPlan")
