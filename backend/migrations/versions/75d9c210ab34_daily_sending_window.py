"""Add daily outbound window without changing existing approvals or queues."""

import sqlalchemy as sa
from alembic import op

revision = "75d9c210ab34"
down_revision = "1372277c354d"
branch_labels = None
depends_on = None

FORM_GUARD = """CREATE OR REPLACE FUNCTION approved_form_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Form dispatch evidence cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW) - ARRAY['status','worker_id','lease_expires_at',
                          'started_at','finished_at','delivery_id','reason'])
      IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['status','worker_id','lease_expires_at',
                          'started_at','finished_at','delivery_id','reason'])
     OR (OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at)
     OR (OLD.delivery_id IS NOT NULL AND NEW.delivery_id IS DISTINCT FROM OLD.delivery_id) THEN
    RAISE EXCEPTION 'Immutable form reservation' USING ERRCODE='23514';
  END IF;
  IF NEW.status <> OLD.status AND NOT (
    (OLD.status='queued' AND NEW.status IN ('checking','cancelled','blocked')) OR
    (OLD.status='checking' AND NEW.status IN ('unknown','blocked','cancelled')) OR
    (OLD.status='unknown' AND NEW.status IN ('submitted','failed'))
    /* WINDOW_RETURN */
  ) THEN RAISE EXCEPTION 'Invalid form dispatch transition' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;"""

WINDOW_RETURN = """OR (OLD.status='checking' AND NEW.status='queued'
  AND OLD.started_at IS NULL AND OLD.delivery_id IS NULL
  AND NEW.started_at IS NULL AND NEW.delivery_id IS NULL
  AND NEW.worker_id IS NULL AND NEW.lease_expires_at IS NULL)"""


def upgrade():
    op.execute(FORM_GUARD.replace("/* WINDOW_RETURN */", WINDOW_RETURN))
    op.create_table(
        "sending_windows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_sending_window_singleton"),
        sa.CheckConstraint(
            "start_minute >= 0 AND start_minute < end_minute AND end_minute <= 1440",
            name="ck_sending_window_minutes",
        ),
    )


def downgrade():
    # Only configuration is removed; approvals, attempts and delivery records are retained.
    op.drop_table("sending_windows")
    op.execute(FORM_GUARD.replace("/* WINDOW_RETURN */", ""))
