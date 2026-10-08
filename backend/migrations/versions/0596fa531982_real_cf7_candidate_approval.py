"""Real static CF7 candidate approval, never an execution authorization."""

from alembic import op

revision = "0596fa531982"
down_revision = "75d9c210ab34"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_cf7_real_candidate_not_consumed",
        "approval_requests",
        "delivery_method <> 'cf7_real_candidate_only' OR status <> 'CONSUMED'",
    )
    op.execute("""
    CREATE FUNCTION cf7_real_marker(p jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      SELECT COALESCE(p->>'delivery_method'='cf7_real_candidate_only',false)
        OR COALESCE(p ? 'cf7_real_handoff',false);
    $$;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM approval_requests WHERE delivery_method='cf7_real_candidate_only'
          OR cf7_real_marker(payload_snapshot)) THEN
        RAISE EXCEPTION 'Unprotected real CF7 candidate history; upgrade stopped'
          USING ERRCODE='23514';
      END IF;
    END $$;
    CREATE FUNCTION cf7_real_approval_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE h jsonb; c jsonb;
    BEGIN
      IF TG_OP='UPDATE' AND (OLD.delivery_method='cf7_real_candidate_only' OR
          cf7_real_marker(OLD.payload_snapshot)) THEN
        IF NEW.payload_snapshot IS DISTINCT FROM OLD.payload_snapshot OR
           NEW.payload_hash IS DISTINCT FROM OLD.payload_hash OR
           NEW.payload_version IS DISTINCT FROM OLD.payload_version OR
           NEW.delivery_method IS DISTINCT FROM OLD.delivery_method OR
           NEW.channel IS DISTINCT FROM OLD.channel OR
           NEW.recipient IS DISTINCT FROM OLD.recipient OR
           NEW.project_id IS DISTINCT FROM OLD.project_id OR
           NEW.company_id IS DISTINCT FROM OLD.company_id OR
           NEW.source_draft_id IS DISTINCT FROM OLD.source_draft_id OR
           NEW.form_url IS DISTINCT FROM OLD.form_url OR
           NEW.subject IS DISTINCT FROM OLD.subject OR NEW.body IS DISTINCT FROM OLD.body OR
           NEW.sender IS DISTINCT FROM OLD.sender OR
           NEW.field_values IS DISTINCT FROM OLD.field_values OR
           NEW.created_by_principal_type IS DISTINCT FROM OLD.created_by_principal_type OR
           NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id OR
           NEW.created_by_agent_id IS DISTINCT FROM OLD.created_by_agent_id OR
           NEW.expires_at IS DISTINCT FROM OLD.expires_at OR
           NEW.created_at IS DISTINCT FROM OLD.created_at OR
           NEW.proposal_id IS DISTINCT FROM OLD.proposal_id OR
           NEW.canonicalization_version IS DISTINCT FROM OLD.canonicalization_version THEN
          RAISE EXCEPTION 'Real CF7 candidate payload is immutable' USING ERRCODE='23514';
        END IF;
      END IF;
      IF NEW.delivery_method='cf7_real_candidate_only' OR cf7_real_marker(NEW.payload_snapshot) THEN
        h := NEW.payload_snapshot->'cf7_real_handoff'; c := h->'snapshot'->'contract';
        IF NEW.status='CONSUMED' OR
           NEW.delivery_method IS DISTINCT FROM 'cf7_real_candidate_only' OR
           NEW.channel IS DISTINCT FROM 'form' OR NEW.recipient IS NOT NULL OR
           NEW.source_draft_id IS NULL OR
           NEW.created_by_principal_type IS DISTINCT FROM 'HUMAN' OR
           NEW.created_by_user_id IS NULL OR
           NEW.created_by_agent_id IS NOT NULL OR NEW.payload_version<>1 OR
           NEW.payload_snapshot->>'delivery_method' IS DISTINCT FROM NEW.delivery_method OR
           NEW.payload_snapshot->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
           NEW.payload_snapshot->>'company_id' IS DISTINCT FROM NEW.company_id::text OR
           NEW.payload_snapshot->>'source_draft_id' IS DISTINCT FROM NEW.source_draft_id::text OR
           h->>'status' IS DISTINCT FROM 'PREPARATION_ONLY' OR
           h->'execution_allowed' IS DISTINCT FROM 'false'::jsonb OR
           h->'eligible_for_approval' IS DISTINCT FROM 'false'::jsonb OR
           h->'authorization_type' IS DISTINCT FROM 'null'::jsonb OR
           h->'approval_request_created' IS DISTINCT FROM 'false'::jsonb OR
           h->'snapshot'->>'definition_version' IS DISTINCT FROM
             'real-cf7-human-handoff-preview-v1' OR
           c->>'source_kind' IS DISTINCT FROM 'REAL_SITE_STATIC_HTML' OR
           c->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
           c->>'company_id' IS DISTINCT FROM NEW.company_id::text OR
           c->>'draft_id' IS DISTINCT FROM NEW.source_draft_id::text OR
           c->>'form_url' IS DISTINCT FROM NEW.form_url OR
           NOT EXISTS (SELECT 1 FROM companies co JOIN outreach_drafts d ON d.company_id=co.id
             JOIN form_profiles f ON f.company_id=co.id WHERE co.id=NEW.company_id AND
             co.project_id=NEW.project_id AND d.id=NEW.source_draft_id AND d.channel='form' AND
             f.id::text=c->>'profile_id') THEN
          RAISE EXCEPTION 'Real CF7 candidate binding or non-execution required'
            USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_real_approval BEFORE INSERT OR UPDATE ON approval_requests
      FOR EACH ROW EXECUTE FUNCTION cf7_real_approval_guard();
    CREATE FUNCTION cf7_real_execution_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p jsonb; a uuid;
    BEGIN
      IF TG_TABLE_NAME='approved_form_dispatches' THEN
        p := NEW.payload_snapshot; a := NEW.approval_id;
      ELSIF TG_TABLE_NAME='approved_email_reservations' THEN
        p := NEW.envelope; a := NEW.approval_id;
      ELSE
        p := NEW.execution_authorization;
        BEGIN a := (p->>'approval_id')::uuid;
        EXCEPTION WHEN invalid_text_representation THEN a := NULL; END;
      END IF;
      IF cf7_real_marker(p) OR EXISTS (SELECT 1 FROM approval_requests r WHERE r.id=a AND
          (r.delivery_method='cf7_real_candidate_only' OR cf7_real_marker(r.payload_snapshot))) THEN
        RAISE EXCEPTION 'Real CF7 candidate cannot authorize execution' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_real_form_reservation BEFORE INSERT OR UPDATE ON approved_form_dispatches
      FOR EACH ROW EXECUTE FUNCTION cf7_real_execution_guard();
    CREATE TRIGGER cf7_real_email_reservation BEFORE INSERT OR UPDATE ON approved_email_reservations
      FOR EACH ROW EXECUTE FUNCTION cf7_real_execution_guard();
    CREATE TRIGGER cf7_real_delivery BEFORE INSERT OR UPDATE ON form_deliveries
      FOR EACH ROW EXECUTE FUNCTION cf7_real_execution_guard();
    """)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM approval_requests WHERE delivery_method='cf7_real_candidate_only' OR
        cf7_real_marker(payload_snapshot)) THEN
        RAISE EXCEPTION 'Real CF7 candidate history prevents downgrade' USING ERRCODE='23514';
      END IF;
    END $$;
    DROP TRIGGER cf7_real_delivery ON form_deliveries;
    DROP TRIGGER cf7_real_email_reservation ON approved_email_reservations;
    DROP TRIGGER cf7_real_form_reservation ON approved_form_dispatches;
    DROP FUNCTION cf7_real_execution_guard();
    DROP TRIGGER cf7_real_approval ON approval_requests;
    DROP FUNCTION cf7_real_approval_guard();
    DROP FUNCTION cf7_real_marker(jsonb);
    """)
    op.drop_constraint("ck_cf7_real_candidate_not_consumed", "approval_requests", type_="check")
