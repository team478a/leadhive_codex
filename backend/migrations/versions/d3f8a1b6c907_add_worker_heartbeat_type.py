"""Add an explicit type to worker heartbeats."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f8a1b6c907"
down_revision: Union[str, None] = "a71c4f09d2e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "worker_heartbeats",
        sa.Column(
            "worker_type",
            sa.String(length=32),
            server_default="application",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("worker_heartbeats", "worker_type")
