"""Options for live Tushare doc page / min_points sync."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

DocPagesScope = Literal["resolved", "all"]


@dataclass
class DocPagesSyncOptions:
    scope: DocPagesScope = "all"
    doc_ids: list[int] | None = None
    sleep_seconds: float = 0.35
    use_playwright: bool = True
    login_if_needed: bool = True
    rebuild_registry: bool = True
    patch_sidebar: bool = True
    reconcile_overrides: bool = True
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DocPagesSyncOptions:
        if not data:
            return cls()
        doc_ids = data.get("doc_ids")
        return cls(
            scope=data.get("scope", "all"),
            doc_ids=[int(x) for x in doc_ids] if doc_ids else None,
            sleep_seconds=float(data.get("sleep_seconds", 0.35)),
            use_playwright=bool(data.get("use_playwright", True)),
            login_if_needed=bool(data.get("login_if_needed", True)),
            rebuild_registry=bool(data.get("rebuild_registry", True)),
            patch_sidebar=bool(data.get("patch_sidebar", True)),
            reconcile_overrides=bool(data.get("reconcile_overrides", True)),
            dry_run=bool(data.get("dry_run", False)),
        )
