"""SyncHandler registry."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional


@dataclass
class SyncContext:
    data_type: str
    source_id: int
    start_date: date
    end_date: date
    extra: Optional[Dict[str, Any]] = None
    batch_mode: str = "default"


@dataclass
class CollectResult:
    rows_upserted: int = 0
    api_calls: int = 0
    message: str = ""
    detail_json: dict[str, Any] | None = None


class SyncHandler(ABC):
    @abstractmethod
    def collect(self, ctx: SyncContext) -> CollectResult:
        raise NotImplementedError


DATA_TYPE_HANDLERS: Dict[str, SyncHandler] = {}


def register_handler(data_type: str, handler: SyncHandler) -> None:
    DATA_TYPE_HANDLERS[data_type] = handler


def get_handler(data_type: str) -> Optional[SyncHandler]:
    handler = DATA_TYPE_HANDLERS.get(data_type)
    if handler is not None:
        return handler
    from app.services.tia.constants import resolve_canonical_data_type

    canonical = resolve_canonical_data_type(data_type)
    if canonical != data_type:
        return DATA_TYPE_HANDLERS.get(canonical)
    return None
