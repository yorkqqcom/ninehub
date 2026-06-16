"""TIA L2 scaffold package generation."""

import io
import json
import zipfile

from app.models.tia_override import TiaOverride
from app.services.tia.constants import api_to_data_type
from app.services.tia.scan.tushare_doc_registry import resolve_api_meta


class TiaScaffoldService:
    def build_zip(self, override: TiaOverride) -> bytes:
        api_name = override.api_name
        data_type = override.data_type
        from app.catalog.tia_probe_registry import OFFICIAL_ONLY_API_PROBES

        meta = OFFICIAL_ONLY_API_PROBES.get(api_name) or resolve_api_meta(api_name) or {}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            meta = {
                "data_type": data_type,
                "api_name": api_name,
                "domain": override.domain,
                "label": override.label,
                "min_points": override.min_points,
                "table_name": override.table_name or f"tia_{api_name}",
            }
            zf.writestr("meta.json", json.dumps(meta, indent=2, ensure_ascii=False))
            zf.writestr(
                f"migrations/template_{api_name}.py",
                self._migration_template(api_name, override.table_name or f"tia_{api_name}"),
            )
            zf.writestr(
                f"collectors/{api_name}_collector.py",
                self._collector_stub(api_name, meta),
            )
            zf.writestr(
                f"sync/handlers/{data_type}_handler.py",
                self._handler_stub(api_name, data_type),
            )
        return buffer.getvalue()

    def _migration_template(self, api_name: str, table_name: str) -> str:
        return f'''"""Template migration for TIA {api_name}."""

from alembic import op
import sqlalchemy as sa

revision = "tia_{api_name}"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "{table_name}",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("{table_name}")
'''

    def _collector_stub(self, api_name: str, quota: dict) -> str:
        return f'''"""Collector stub for {api_name} (min_points={quota.get("min_points", 0)})."""

from app.services.collectors.base import BaseCollector


class {api_name.title()}Collector(BaseCollector):
    source_type = "tushare"

    def fetch_daily(self, stock_codes, start_date, end_date):
        raise NotImplementedError("Implement via TIA L3")
'''

    def _handler_stub(self, api_name: str, data_type: str) -> str:
        return f'''"""SyncHandler stub for {data_type}."""

from app.sync.handlers import CollectResult, SyncContext, SyncHandler, register_handler


class {data_type.title()}Handler(SyncHandler):
    def collect(self, ctx: SyncContext) -> CollectResult:
        return CollectResult(message="stub for {api_name}")


register_handler("{data_type}", {data_type.title()}Handler())
'''
