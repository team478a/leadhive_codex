import sqlalchemy as sa
from alembic import op

revision = "f14c9b7a6d20"
down_revision = "c4e8a1d7f2b9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("worker_heartbeats"):
        op.create_table(
            "worker_heartbeats",
            sa.Column("instance_id", sa.String(length=255), nullable=False),
            sa.Column("host_name", sa.String(length=255), nullable=False),
            sa.Column("commit_id", sa.String(length=40), nullable=False),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("instance_id"),
        )

    index_names = {
        index["name"] for index in sa.inspect(bind).get_indexes("worker_heartbeats")
    }
    if "ix_worker_heartbeats_last_seen_at" not in index_names:
        op.create_index(
            "ix_worker_heartbeats_last_seen_at",
            "worker_heartbeats",
            ["last_seen_at"],
        )


def downgrade():
    op.drop_index("ix_worker_heartbeats_last_seen_at", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
