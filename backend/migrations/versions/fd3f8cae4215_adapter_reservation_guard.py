"""Adapter reservations remain non-executable in the preparation phase."""

from alembic import op

revision = "fd3f8cae4215"
down_revision = "fc2e7b9d3104"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_adapter_reservation_not_started",
        "approved_form_dispatches",
        "payload_snapshot->>'delivery_method' <> 'form_adapter' OR "
        "(status IN ('queued','blocked','cancelled') AND started_at IS NULL "
        "AND delivery_id IS NULL AND worker_id IS NULL)",
    )


def downgrade():
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM approved_form_dispatches
               WHERE payload_snapshot->>'delivery_method'='form_adapter') THEN
      RAISE EXCEPTION 'Adapter reservation evidence exists; downgrade forbidden'
        USING ERRCODE='23514';
    END IF; END $$;""")
    op.drop_constraint(
        "ck_adapter_reservation_not_started", "approved_form_dispatches", type_="check"
    )
