"""Add an explicit type to worker heartbeats."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f8a1b6c907"
down_revision: Union[str, None] = "a71c4f09d2e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("worker_heartbeats")}
    if "worker_type" not in column_names:
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
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("worker_heartbeats")}
    if "worker_type" in column_names:
        op.drop_column("worker_heartbeats", "worker_type")
