"""Catalog data type registry — drives tasks and sync handlers."""

from dataclasses import dataclass, field
from typing import List, Optional

from app.schemas.catalog import CatalogColumnMeta, CatalogFilterMeta


@dataclass
class DataTypeEntry:
    data_type: str
    domain: str
    label: str
    table_name: Optional[str] = None
    is_activated: bool = False
    browse_enabled: bool = False
    chart_type: Optional[str] = None
    min_points: int = 0
    columns: List[CatalogColumnMeta] = field(default_factory=list)
    filters: List[CatalogFilterMeta] = field(default_factory=list)
    sync_start_date_override: Optional[str] = None


# Seven business domains for sidebar navigation (B-01)
DOMAINS: List[tuple[str, str]] = [
    ("market", "行情"),
    ("basic", "基础"),
    ("financial", "财务"),
    ("reference", "参考"),
    ("feature", "特色"),
    ("index", "指数"),
    ("macro", "宏观"),
]

# Runtime catalog: empty at bootstrap; TIA L3 activation registers entries.
CATALOG_REGISTRY: dict[str, DataTypeEntry] = {}


def get_data_type_entry(data_type: str) -> Optional[DataTypeEntry]:
    return CATALOG_REGISTRY.get(data_type)


def list_data_types(domain: Optional[str] = None) -> List[DataTypeEntry]:
    entries = list(CATALOG_REGISTRY.values())
    if domain:
        entries = [e for e in entries if e.domain == domain]
    return entries


def list_domains() -> List[tuple[str, str]]:
    return DOMAINS


def register_catalog_entry(entry: DataTypeEntry) -> None:
    """Runtime L3 registration — also used when loading overrides at startup."""
    CATALOG_REGISTRY[entry.data_type] = entry


def entry_from_override(
    api_name: str,
    data_type: str,
    domain: str,
    label: str,
    min_points: int,
    table_name: str | None,
    is_activated: bool,
    doc_url: str | None = None,
    columns: List[CatalogColumnMeta] | None = None,
    filters: List[CatalogFilterMeta] | None = None,
    browse_enabled: bool = False,
) -> DataTypeEntry:
    if columns is None:
        columns = [
            CatalogColumnMeta(key="stock_code", label="代码", type="string"),
            CatalogColumnMeta(key="trade_date", label="日期", type="date"),
        ]
        if api_name == "income":
            columns = [
                CatalogColumnMeta(key="stock_code", label="代码", type="string"),
                CatalogColumnMeta(key="end_date", label="报告期", type="date"),
                CatalogColumnMeta(key="revenue", label="营收", type="number"),
            ]
    if filters is None:
        filters = [
            CatalogFilterMeta(key="stock_code", label="股票代码", filter_type="stock_picker"),
        ]
    return DataTypeEntry(
        data_type=data_type,
        domain=domain,
        label=label,
        table_name=table_name,
        is_activated=is_activated,
        browse_enabled=browse_enabled,
        min_points=min_points,
        columns=columns,
        filters=filters,
    )
