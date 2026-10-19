"""Add content-free feature usage events for operational reporting."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "21501a000002"
down_revision = "21501a000001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feature_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column(
            "outcome", sa.String(length=20), server_default="completed", nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "event_type IN ('collection_condition_proposal', 'pc_input_trial_issued', "
            "'pc_input_report_recorded', 'live_input_trial_issued', 'live_input_report_recorded')",
            name="ck_feature_usage_event_type",
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'failed')", name="ck_feature_usage_outcome"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feature_usage_events_created_type",
        "feature_usage_events",
        ["created_at", "event_type"],
    )


def downgrade():
    op.drop_index("ix_feature_usage_events_created_type", table_name="feature_usage_events")
    op.drop_table("feature_usage_events")
