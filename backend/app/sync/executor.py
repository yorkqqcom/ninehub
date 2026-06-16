"""Sync executor orchestrates collect → load."""

from app.core.exceptions import NotFoundError, ValidationError
from app.sync.handlers import CollectResult, DATA_TYPE_HANDLERS, SyncContext


class SyncExecutor:
    def run(self, ctx: SyncContext) -> CollectResult:
        handler = DATA_TYPE_HANDLERS.get(ctx.data_type)
        if handler is None:
            raise NotFoundError(f"No SyncHandler for data_type={ctx.data_type}")
        if ctx.end_date < ctx.start_date:
            raise ValidationError("end_date must be >= start_date")
        return handler.collect(ctx)
