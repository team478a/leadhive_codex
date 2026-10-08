"""prevent active operation duplicates

Revision ID: c1d9f6a2b4e8
Revises: 8e2c4a7f1b90
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d9f6a2b4e8"
down_revision: str | None = "8e2c4a7f1b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT project_id, operation_type, count(*)
            FROM operation_jobs
            WHERE status IN ('queued', 'running')
            GROUP BY project_id, operation_type
            HAVING count(*) > 1
            LIMIT 1
            """
            )
        )
        .first()
    )
    if duplicate:
        raise RuntimeError(
            "Active operation duplicates must be resolved before applying c1d9f6a2b4e8."
        )
    op.create_index(
        "uq_operation_jobs_active_project_type",
        "operation_jobs",
        ["project_id", "operation_type"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_operation_jobs_active_project_type", table_name="operation_jobs")
