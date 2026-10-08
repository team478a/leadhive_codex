"""Add Human-authorized form evidence without altering prior migrations."""

import sqlalchemy as sa
from alembic import op

revision = "f8b25ea3c649"
down_revision = "f7a14d92b538"
branch_labels = None
depends_on = None

EVIDENCE_MARKER = (
    "            ) THEN\n                RAISE EXCEPTION 'Durable dispatch evidence required'"
)
FORM_EVIDENCE = """            ) AND NOT EXISTS (
                SELECT 1 FROM approved_form_dispatches r
                JOIN form_deliveries d ON d.id = r.delivery_id
                WHERE r.approval_id = NEW.id AND NEW.channel = 'form'
                  AND r.status = 'unknown' AND d.status = 'unknown'
                  AND r.started_at IS NOT NULL AND r.payload_hash = NEW.payload_hash
                  AND (r.payload_snapshot->>'payload_version')::integer = NEW.payload_version
            ) THEN
                RAISE EXCEPTION 'Durable dispatch evidence required'"""


def update_evidence(old, new):
    definition = op.get_bind().scalar(
        sa.text("SELECT pg_get_functiondef('a2_immutable_approval()'::regprocedure)")
    )
    if definition.count(old) != 1:
        raise RuntimeError("Unexpected approval evidence guard; migration stopped")
    op.execute(definition.replace(old, new, 1))


def upgrade():
    op.add_column(
        "form_profiles", sa.Column("action_url", sa.Text(), nullable=False, server_default="")
    )
    op.alter_column("form_profiles", "action_url", server_default=None)
    op.create_table(
        "approved_form_dispatches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "approval_id",
            sa.Uuid(),
            sa.ForeignKey("approval_requests.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("draft_id", sa.Uuid(), sa.ForeignKey("outreach_drafts.id"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload_snapshot", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("form_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("worker_id", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("form_deliveries.id")),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('queued','checking','submitted','failed','unknown','blocked','cancelled')",
            name="ck_approved_form_status",
        ),
    )
    for column in ("project_id", "company_id", "form_url", "status", "started_at"):
        op.create_index(
            f"ix_approved_form_dispatches_{column}", "approved_form_dispatches", [column]
        )
    update_evidence(EVIDENCE_MARKER, FORM_EVIDENCE)
    op.execute("""CREATE FUNCTION approved_form_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
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
      ) THEN RAISE EXCEPTION 'Invalid form dispatch transition' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER approved_form_guard BEFORE UPDATE OR DELETE ON approved_form_dispatches
    FOR EACH ROW EXECUTE FUNCTION approved_form_immutable();""")


def downgrade():
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM approved_form_dispatches) THEN
      RAISE EXCEPTION 'Form dispatch evidence exists; downgrade forbidden';
    END IF; END $$;""")
    update_evidence(FORM_EVIDENCE, EVIDENCE_MARKER)
    op.execute(
        "DROP TRIGGER approved_form_guard ON approved_form_dispatches; "
        "DROP FUNCTION approved_form_immutable();"
    )
    op.drop_table("approved_form_dispatches")
    op.drop_column("form_profiles", "action_url")
