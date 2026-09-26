"""verify form delivery completion

Revision ID: 4f7b2c9d1a60
Revises: 6a1d9e4c2b70
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f7b2c9d1a60"
down_revision: str | None = "6a1d9e4c2b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "form_deliveries",
        sa.Column("final_url", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "form_deliveries",
        sa.Column("confirmation_used", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "form_deliveries",
        sa.Column("completion_evidence", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("form_deliveries", "completion_evidence")
    op.drop_column("form_deliveries", "confirmation_used")
    op.drop_column("form_deliveries", "final_url")
