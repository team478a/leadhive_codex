"""Add shared access slots and worker scope diagnostics."""

import sqlalchemy as sa
from alembic import op

revision = "224a00000001"
down_revision = "223a00000001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "host_access_slots" not in inspector.get_table_names():
        op.create_table(
            "host_access_slots",
            sa.Column("host", sa.String(length=255), nullable=False),
            sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("host"),
        )
    columns = {column["name"] for column in inspector.get_columns("worker_heartbeats")}
    if "include_operation_types" not in columns:
        op.add_column(
            "worker_heartbeats",
            sa.Column(
                "include_operation_types", sa.String(length=1000), server_default="", nullable=False
            ),
        )
    if "exclude_operation_types" not in columns:
        op.add_column(
            "worker_heartbeats",
            sa.Column(
                "exclude_operation_types", sa.String(length=1000), server_default="", nullable=False
            ),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("worker_heartbeats")}
    if "exclude_operation_types" in columns:
        op.drop_column("worker_heartbeats", "exclude_operation_types")
    if "include_operation_types" in columns:
        op.drop_column("worker_heartbeats", "include_operation_types")
    if "host_access_slots" in inspector.get_table_names():
        op.drop_table("host_access_slots")
