"""TIA full-scan types and options."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ScanMode = Literal["catalog", "full"]
ProbeScope = Literal["local_and_new", "all"]
IndexSource = Literal["auto", "document2", "doc14", "bundled", "live"]
IndexScope = Literal["mixed", "stock_a"]


@dataclass
class ScanOptions:
    """Provider-agnostic scan configuration."""

    provider: str = "tushare"
    mode: ScanMode = "full"
    index_scope: IndexScope = "stock_a"
    probe: bool = True
    probe_scope: ProbeScope = "all"
    probe_limit: int = 500
    probe_unlimited: bool = False
    index_source: IndexSource = "document2"
    sync_doc_pages: bool = False
    sync_doc_specs: bool = True
    sync_sdk_scan: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ScanOptions:
        if not data:
            return cls()
        mode = data.get("mode", "full")
        sync_doc_pages = data.get("sync_doc_pages")
        if sync_doc_pages is None:
            sync_doc_pages = False
        sync_doc_specs = data.get("sync_doc_specs")
        if sync_doc_specs is None:
            sync_doc_specs = mode == "full"
        sync_sdk_scan = data.get("sync_sdk_scan")
        if sync_sdk_scan is None:
            sync_sdk_scan = mode == "full"
        return cls(
            provider=str(data.get("provider", "tushare")),
            mode=mode,
            index_scope=data.get("index_scope", "stock_a"),
            probe=bool(data.get("probe", True)),
            probe_scope=data.get("probe_scope", "local_and_new"),
            probe_limit=int(data.get("probe_limit", 500)),
            probe_unlimited=bool(data.get("probe_unlimited", False)),
            index_source=data.get("index_source", "document2"),
            sync_doc_pages=bool(sync_doc_pages),
            sync_doc_specs=bool(sync_doc_specs),
            sync_sdk_scan=bool(sync_sdk_scan),
        )


@dataclass
class OfficialApiEntry:
    api: str
    doc_id: int | None = None
    category: str | None = None
    label: str | None = None
    min_points: int | None = None
    probe_category: str | None = None
    doc_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OfficialApiEntry:
        doc_id = data.get("doc_id")
        return cls(
            api=str(data["api"]),
            doc_id=int(doc_id) if doc_id is not None else None,
            category=data.get("category"),
            label=data.get("label"),
            min_points=data.get("min_points"),
            probe_category=data.get("probe_category"),
            doc_url=data.get("doc_url"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OfficialIndexSnapshot:
    provider: str
    apis: list[OfficialApiEntry]
    source: str = "bundled"
    version: str | None = None
    total: int = 0
    scope: str | None = None
    sidebar_link_total: int = 0
    resolved_api_count: int = 0
    unresolved_doc_ids: list[int] = field(default_factory=list)
    doc_ids_traversed: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.total == 0:
            self.total = len(self.apis)
        if self.resolved_api_count == 0 and self.apis:
            self.resolved_api_count = len(self.apis)

    def api_names(self) -> list[str]:
        return sorted(entry.api for entry in self.apis)

    def as_map(self) -> dict[str, OfficialApiEntry]:
        return {entry.api: entry for entry in self.apis}

    def as_doc_id_map(self) -> dict[int, OfficialApiEntry]:
        out: dict[int, OfficialApiEntry] = {}
        for entry in self.apis:
            if entry.doc_id is not None:
                out[int(entry.doc_id)] = entry
        return out


@dataclass
class CatalogDiffResult:
    local_apis: list[str]
    official_apis: list[str]
    new_on_official: list[str]
    missing_from_official: list[str]
    unchanged: list[str]
    official_snapshot: OfficialIndexSnapshot

    def to_dict(self) -> dict[str, Any]:
        snap = self.official_snapshot
        return {
            "local_count": len(self.local_apis),
            "official_count": len(self.official_apis),
            "new_on_official": self.new_on_official,
            "missing_from_official": self.missing_from_official,
            "unchanged": self.unchanged,
            "official_index_source": snap.source,
            "official_index_version": snap.version,
            "official_index_total": snap.total,
            "official_index_scope": getattr(snap, "scope", None),
            "sidebar_link_total": getattr(snap, "sidebar_link_total", 0),
            "resolved_api_count": getattr(snap, "resolved_api_count", snap.total),
            "unresolved_doc_count": len(getattr(snap, "unresolved_doc_ids", []) or []),
            "doc_ids_traversed": len(getattr(snap, "doc_ids_traversed", []) or []),
        }
