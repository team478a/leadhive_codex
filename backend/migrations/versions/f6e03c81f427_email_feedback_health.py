"""Email evidence and project circuit breaker, additive only."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6e03c81f427"
down_revision = "f5d92b70e316"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "email_feedback_events",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("project_id", postgresql.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "delivery_id", postgresql.UUID(), sa.ForeignKey("email_deliveries.id"), nullable=False
        ),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_user_id", postgresql.UUID(), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("source", "event_key", name="uq_email_feedback_source_key"),
        sa.CheckConstraint(
            "kind IN ('delivered','hard_bounce','soft_bounce','complaint','unsubscribe')",
            name="ck_email_feedback_kind",
        ),
        sa.CheckConstraint("source IN ('HUMAN','PROVIDER')", name="ck_email_feedback_source"),
    )
    for column in ("project_id", "delivery_id"):
        op.create_index(f"ix_email_feedback_events_{column}", "email_feedback_events", [column])
    op.create_table(
        "email_health_states",
        sa.Column(
            "project_id",
            postgresql.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", postgresql.UUID(), sa.ForeignKey("users.id")),
        sa.Column("review_failures", sa.Integer(), nullable=False),
        sa.Column("review_locked_until", sa.DateTime(timezone=True)),
    )
    op.execute("""
        CREATE FUNCTION protect_email_feedback() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'email feedback is append-only'; END; $$
    """)
    op.execute("""
        CREATE TRIGGER email_feedback_append_only BEFORE UPDATE OR DELETE
        ON email_feedback_events FOR EACH ROW EXECUTE FUNCTION protect_email_feedback()
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM email_feedback_events)
          OR EXISTS (SELECT 1 FROM email_health_states) THEN
          RAISE EXCEPTION 'email health history exists; restore backup instead';
        END IF; END; $$
    """)
    op.drop_table("email_health_states")
    op.drop_table("email_feedback_events")
    op.execute("DROP FUNCTION protect_email_feedback()")
