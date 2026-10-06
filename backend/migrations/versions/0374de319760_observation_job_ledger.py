"""Add managed observation lifecycle ledger; no execution registration."""

import sqlalchemy as sa
from alembic import op

revision = "0374de319760"
down_revision = "0263cd208659"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "form_observation_job_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "operation_job_id", sa.Uuid(), sa.ForeignKey("operation_jobs.id"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Uuid()),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("principal_type", sa.String(10), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(30), nullable=False),
        sa.Column("before_status", sa.String(12)),
        sa.Column("after_status", sa.String(12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('QUEUED','CLAIMED','CANCEL_REQUESTED','CANCELLED',"
            "'COMPLETED','FAILED','RECOVERED')",
            name="ck_observation_job_event_type",
        ),
        sa.CheckConstraint(
            "reason_code IN ('QUEUED','CLAIMED','CANCELLED','EVIDENCE_SAVED',"
            "'CLAIM_REJECTED','OBSERVATION_FAILED','BINDING_CHANGED','LEASE_CHANGED',"
            "'WORKER_LOST','PERMISSION_CHANGED','SOURCE_CHANGED','LAB_DISABLED')",
            name="ck_observation_job_reason",
        ),
        sa.CheckConstraint(
            "(principal_type = 'HUMAN' AND actor_user_id IS NOT NULL) OR "
            "(principal_type = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_observation_job_actor",
        ),
        sa.CheckConstraint("attempt_number BETWEEN 0 AND 1000", name="ck_observation_job_attempt"),
        sa.CheckConstraint(
            "before_status IS NULL OR before_status IN "
            "('queued','running','completed','failed','cancelled')",
            name="ck_observation_job_before",
        ),
        sa.CheckConstraint(
            "after_status IN ('queued','running','completed','failed','cancelled')",
            name="ck_observation_job_after",
        ),
    )
    for column in ("project_id", "company_id", "operation_job_id"):
        op.create_index(
            "ix_form_observation_job_events_" + column, "form_observation_job_events", [column]
        )
    op.execute("""
CREATE TRIGGER observation_job_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON form_observation_job_events FOR EACH STATEMENT EXECUTE FUNCTION form_observation_immutable();
CREATE FUNCTION form_observation_job_event_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE j operation_jobs%ROWTYPE; cid uuid;
BEGIN
 IF right(current_database(), 5) <> '_test' THEN
 RAISE EXCEPTION 'Observation job ledger requires test database' USING ERRCODE='23514'; END IF;
 SELECT * INTO j FROM operation_jobs WHERE id=NEW.operation_job_id FOR SHARE;
 IF NOT FOUND OR j.operation_type <> 'cf7_observation' OR j.project_id <> NEW.project_id
 OR j.payload->>'company_id' IS DISTINCT FROM NEW.company_id::text
 OR j.payload->>'run_id' IS DISTINCT FROM NEW.run_id::text
 OR j.attempt_count <> NEW.attempt_number OR j.status <> NEW.after_status
 OR j.worker_id IS DISTINCT FROM NEW.worker_id THEN
 RAISE EXCEPTION 'Observation job ledger binding mismatch' USING ERRCODE='23514'; END IF;
 SELECT project_id INTO cid FROM companies WHERE id=NEW.company_id FOR SHARE;
 IF NOT FOUND OR cid <> NEW.project_id THEN
 RAISE EXCEPTION 'Observation job company mismatch' USING ERRCODE='23514'; END IF;
 IF (NEW.event_type='QUEUED' AND (NEW.before_status IS NOT NULL OR NEW.after_status<>'queued'))
 OR (NEW.event_type='CLAIMED' AND (NEW.before_status IS DISTINCT FROM 'queued'
 OR NEW.after_status<>'running'))
 OR (NEW.event_type='CANCEL_REQUESTED' AND (NEW.before_status IS DISTINCT FROM 'running'
 OR NEW.after_status<>'running' OR NOT j.cancel_requested))
 OR (NEW.event_type='CANCELLED' AND NEW.after_status<>'cancelled')
 OR (NEW.event_type='COMPLETED' AND NEW.after_status<>'completed')
 OR (NEW.event_type IN ('FAILED','RECOVERED')
 AND NEW.after_status NOT IN ('failed','cancelled')) THEN
 RAISE EXCEPTION 'Observation job ledger state mismatch' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER observation_job_event_binding BEFORE INSERT ON form_observation_job_events
FOR EACH ROW EXECUTE FUNCTION form_observation_job_event_binding();
""")


def downgrade():
    op.execute("DROP FUNCTION form_observation_job_event_binding() CASCADE")
    op.drop_table("form_observation_job_events")
