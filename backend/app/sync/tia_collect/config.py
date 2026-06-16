"""Collect configuration merged from schema and sync profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.tia.sync_profiles import SyncProfile


@dataclass(frozen=True)
class CollectConfig:
    max_codes_per_run: int = 50
    max_api_calls_per_run: int = 200
    batch_size: int = 1


def resolve_collect_config(schema: dict[str, Any], profile: SyncProfile) -> CollectConfig:
    collect = schema.get("collect") or {}
    return CollectConfig(
        max_codes_per_run=int(collect.get("max_codes_per_run", profile.max_codes_per_run)),
        max_api_calls_per_run=int(
            collect.get("max_api_calls_per_run", profile.max_api_calls_per_run)
        ),
        batch_size=max(1, int(collect.get("batch_size", 1))),
    )
