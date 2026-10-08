"""Permit controlled-test consumption only with matching durable Human evidence."""

import sqlalchemy as sa
from alembic import op

revision = "fe409dbf5326"
down_revision = "fd3f8cae4215"
branch_labels = None
depends_on = None

RESERVATION = """payload_snapshot->>'delivery_method' <> 'form_adapter' OR
(status IN ('queued','blocked','cancelled') AND started_at IS NULL
 AND delivery_id IS NULL AND worker_id IS NULL) OR
(current_database() ~ '_test$' AND
 payload_snapshot->'adapter_plan'->>'environment' = 'CONTROLLED_LAB' AND
 ((status='checking' AND started_at IS NULL AND delivery_id IS NULL
   AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL) OR
  (status IN ('unknown','submitted','failed') AND started_at IS NOT NULL
   AND delivery_id IS NOT NULL AND worker_id IS NOT NULL)))"""


def upgrade():
    op.add_column(
        "form_deliveries", sa.Column("execution_authorization", sa.dialects.postgresql.JSONB())
    )
    op.create_check_constraint(
        "ck_adapter_delivery_lab",
        "form_deliveries",
        "delivery_method <> 'adapter' OR (current_database() ~ '_test$' "
        "AND execution_authorization IS NOT NULL)",
    )
    for table, name, expression in (
        (
            "approval_requests",
            "ck_adapter_contract_not_consumed",
            "delivery_method <> 'form_adapter' OR status <> 'CONSUMED' OR "
            "current_database() ~ '_test$'",
        ),
        ("approved_form_dispatches", "ck_adapter_reservation_not_started", RESERVATION),
        (
            "form_deliveries",
            "ck_form_delivery_method",
            "delivery_method IN ('direct','codex_assisted','adapter')",
        ),
        (
            "outreach_draft_approvals",
            "ck_outreach_draft_approval_type",
            "approval_type IN ('email','form_direct','form_codex','form_adapter')",
        ),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, expression)
    op.execute("""CREATE FUNCTION controlled_adapter_consumption() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.delivery_method='form_adapter' AND NEW.status='CONSUMED' THEN
        IF TG_OP='INSERT' THEN
          RAISE EXCEPTION 'Controlled adapter evidence required'
            USING ERRCODE='23514', CONSTRAINT='ck_adapter_contract_not_consumed';
        END IF;
        IF OLD.status <> 'APPROVED' OR current_database() !~ '_test$' OR NOT EXISTS (
          SELECT 1 FROM approved_form_dispatches r
          JOIN form_deliveries d ON d.id=r.delivery_id
          JOIN companies c ON c.id=NEW.company_id
          JOIN outreach_drafts t ON t.id=NEW.source_draft_id
          JOIN form_profiles f ON f.id=d.form_profile_id
          JOIN human_approval_proofs h ON h.request_id=NEW.id
          WHERE r.approval_id=NEW.id AND NEW.channel='form'
            AND r.status='unknown' AND d.status='unknown' AND d.delivery_method='adapter'
            AND r.started_at IS NOT NULL AND r.worker_id IS NOT NULL
            AND r.project_id=NEW.project_id AND c.project_id=NEW.project_id
            AND r.company_id=NEW.company_id AND d.company_id=NEW.company_id
            AND t.company_id=NEW.company_id AND f.company_id=NEW.company_id
            AND r.draft_id=NEW.source_draft_id AND d.draft_id=NEW.source_draft_id
            AND r.payload_hash=NEW.payload_hash AND r.payload_snapshot=NEW.payload_snapshot
            AND NEW.approved_payload_hash=NEW.payload_hash
            AND NEW.approved_payload_version=NEW.payload_version
            AND NEW.approved_by_user_id=d.created_by_user_id
            AND NEW.expires_at > CURRENT_TIMESTAMP
            AND h.user_id=NEW.approved_by_user_id AND h.payload_hash=NEW.payload_hash
            AND h.payload_version=NEW.payload_version AND h.verified_at IS NOT NULL
            AND h.used_at IS NOT NULL
            AND d.execution_authorization=jsonb_build_object(
              'approval_id',NEW.id::text,'payload_hash',NEW.payload_hash,
              'payload_version',NEW.payload_version,
              'adapter_plan_hash',NEW.payload_snapshot->>'adapter_plan_hash')
            AND NEW.payload_snapshot->>'adapter_plan_hash' ~ '^[a-f0-9]{64}$'
            AND NEW.payload_snapshot->'adapter_plan'->>'environment'='CONTROLLED_LAB'
            AND NEW.payload_snapshot->'adapter_plan'->>'adapter_id'='controlled_lab_single_post'
            AND NEW.payload_snapshot->'adapter_plan'->>'adapter_version'='1'
            AND NEW.payload_snapshot->'adapter_plan'->>'project_id'=NEW.project_id::text
            AND NEW.payload_snapshot->'adapter_plan'->>'company_id'=NEW.company_id::text
            AND NEW.payload_snapshot->'adapter_plan'->>'source_draft_id'=NEW.source_draft_id::text
            AND NEW.payload_snapshot->'adapter_plan'->>'form_profile_id'=d.form_profile_id::text
            AND (NEW.payload_snapshot->'adapter_plan'->>'payload_version')::int=NEW.payload_version
            AND NEW.payload_snapshot->'adapter_plan'->>'field_fingerprint'=d.profile_fingerprint
            AND NEW.payload_snapshot->'adapter_plan'->'steps' =
              '[{"kind":"submit","url":"https://fixture.example/submit","method":"POST"}]'::jsonb
            AND r.form_url='https://fixture.example/contact' AND d.form_url=r.form_url
            AND d.action_url='https://fixture.example/submit'
        ) THEN
          RAISE EXCEPTION 'Controlled adapter evidence required'
            USING ERRCODE='23514', CONSTRAINT='ck_adapter_contract_not_consumed';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER controlled_adapter_guard BEFORE INSERT OR UPDATE ON approval_requests
      FOR EACH ROW EXECUTE FUNCTION controlled_adapter_consumption();
    CREATE FUNCTION controlled_delivery_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' AND OLD.delivery_method='adapter' THEN
        RAISE EXCEPTION 'Adapter attempt evidence cannot be deleted' USING ERRCODE='23514';
      ELSIF TG_OP='UPDATE' AND OLD.delivery_method='adapter' THEN
        IF (to_jsonb(NEW)-ARRAY['status','response_status','final_url','confirmation_used',
           'completion_evidence','submitted_at','error_message','result_note','updated_at'])
          IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','response_status',
           'final_url','confirmation_used',
           'completion_evidence','submitted_at','error_message','result_note','updated_at'])
          OR (NEW.status <> OLD.status AND NOT
              (OLD.status='unknown' AND NEW.status IN ('submitted','failed')))
        THEN RAISE EXCEPTION 'Immutable adapter attempt evidence' USING ERRCODE='23514'; END IF;
      END IF;
      IF TG_OP='DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER controlled_delivery_guard BEFORE UPDATE OR DELETE ON form_deliveries
      FOR EACH ROW EXECUTE FUNCTION controlled_delivery_immutable();""")


def downgrade():
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM form_deliveries WHERE delivery_method='adapter') OR
       EXISTS (SELECT 1 FROM approval_requests WHERE
               delivery_method='form_adapter' AND status='CONSUMED') OR
       EXISTS (SELECT 1 FROM approved_form_dispatches WHERE
         payload_snapshot->>'delivery_method'='form_adapter' AND worker_id IS NOT NULL) THEN
      RAISE EXCEPTION 'Adapter execution evidence exists; downgrade forbidden'
        USING ERRCODE='23514';
    END IF; END $$;""")
    op.execute(
        "DROP TRIGGER controlled_adapter_guard ON approval_requests; "
        "DROP FUNCTION controlled_adapter_consumption(); "
        "DROP TRIGGER controlled_delivery_guard ON form_deliveries; "
        "DROP FUNCTION controlled_delivery_immutable();"
    )
    for table, name, expression in (
        (
            "approval_requests",
            "ck_adapter_contract_not_consumed",
            "delivery_method <> 'form_adapter' OR status <> 'CONSUMED'",
        ),
        (
            "approved_form_dispatches",
            "ck_adapter_reservation_not_started",
            "payload_snapshot->>'delivery_method' <> 'form_adapter' OR "
            "(status IN ('queued','blocked','cancelled') AND started_at IS NULL "
            "AND delivery_id IS NULL AND worker_id IS NULL)",
        ),
        (
            "form_deliveries",
            "ck_form_delivery_method",
            "delivery_method IN ('direct','codex_assisted')",
        ),
        (
            "outreach_draft_approvals",
            "ck_outreach_draft_approval_type",
            "approval_type IN ('email','form_direct','form_codex')",
        ),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, expression)
    op.drop_constraint("ck_adapter_delivery_lab", "form_deliveries", type_="check")
    op.drop_column("form_deliveries", "execution_authorization")
