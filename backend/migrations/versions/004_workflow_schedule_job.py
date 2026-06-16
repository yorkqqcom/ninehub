"""004: workflow schedule_cron + workflow_runs.job_id."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_workflow_schedule_job"
down_revision: Union[str, None] = "003_phase1_extensions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workflows", sa.Column("schedule_cron", sa.String(length=64), nullable=True))
    op.add_column(
        "workflows",
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("workflow_runs", sa.Column("job_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_workflow_runs_job_id",
        "workflow_runs",
        "platform_jobs",
        ["job_id"],
        ["id"],
    )
    op.create_index("ix_workflow_runs_job_id", "workflow_runs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_job_id", table_name="workflow_runs")
    op.drop_constraint("fk_workflow_runs_job_id", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "job_id")
    op.drop_column("workflows", "next_run_at")
    op.drop_column("workflows", "schedule_cron")
