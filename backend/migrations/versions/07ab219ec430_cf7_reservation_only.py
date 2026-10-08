"""Separate CF7 reservation reapproval; no execution under any flag."""

from alembic import op

revision = "07ab219ec430"
down_revision = "0596fa531982"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_cf7_reservation_not_consumed",
        "approval_requests",
        "delivery_method <> 'cf7_real_reservation' OR status <> 'CONSUMED'",
    )
    op.create_check_constraint(
        "ck_cf7_reservation_not_started",
        "approved_form_dispatches",
        "payload_snapshot->>'delivery_method' <> 'cf7_real_reservation' OR "
        "(status IN ('queued','blocked','cancelled') AND started_at IS NULL "
        "AND delivery_id IS NULL AND worker_id IS NULL AND lease_expires_at IS NULL)",
    )
    op.execute("""
    CREATE FUNCTION cf7_reservation_marker(p jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
      SELECT COALESCE(p->>'delivery_method'='cf7_real_reservation',false)
        OR COALESCE(p ? 'cf7_reservation_plan',false);
    $$;
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM approval_requests WHERE delivery_method='cf7_real_reservation'
        OR cf7_reservation_marker(payload_snapshot)) THEN
        RAISE EXCEPTION 'Unprotected CF7 reservation history; upgrade stopped'
          USING ERRCODE='23514';
      END IF;
    END $$;
    CREATE FUNCTION cf7_reservation_approval_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p jsonb; source approval_requests%ROWTYPE;
    BEGIN
      IF TG_OP='UPDATE' AND (OLD.delivery_method='cf7_real_reservation' OR
          cf7_reservation_marker(OLD.payload_snapshot)) THEN
        IF ROW(NEW.payload_snapshot,NEW.payload_hash,NEW.payload_version,NEW.delivery_method,
          NEW.channel,NEW.recipient,NEW.project_id,NEW.company_id,NEW.source_draft_id,NEW.form_url,
          NEW.subject,NEW.body,NEW.sender,NEW.field_values,NEW.created_by_principal_type,
          NEW.created_by_user_id,NEW.created_by_agent_id,NEW.expires_at,NEW.created_at,
          NEW.proposal_id,NEW.canonicalization_version) IS DISTINCT FROM
          ROW(OLD.payload_snapshot,OLD.payload_hash,OLD.payload_version,OLD.delivery_method,
          OLD.channel,OLD.recipient,OLD.project_id,OLD.company_id,OLD.source_draft_id,OLD.form_url,
          OLD.subject,OLD.body,OLD.sender,OLD.field_values,OLD.created_by_principal_type,
          OLD.created_by_user_id,OLD.created_by_agent_id,OLD.expires_at,OLD.created_at,
          OLD.proposal_id,OLD.canonicalization_version) THEN
          RAISE EXCEPTION 'CF7 reservation payload is immutable' USING ERRCODE='23514';
        END IF;
      END IF;
      IF NEW.delivery_method='cf7_real_reservation' OR
          cf7_reservation_marker(NEW.payload_snapshot) THEN
        p := NEW.payload_snapshot->'cf7_reservation_plan';
        SELECT * INTO source FROM approval_requests WHERE id::text=p->>'source_approval_id';
        IF source.id IS NULL OR source.delivery_method IS DISTINCT FROM 'cf7_real_candidate_only' OR
          NEW.delivery_method IS DISTINCT FROM 'cf7_real_reservation' OR
          NEW.channel IS DISTINCT FROM 'form' OR NEW.recipient IS NOT NULL OR
          NEW.created_by_principal_type IS DISTINCT FROM 'HUMAN' OR
          NEW.created_by_user_id IS NULL OR
          NEW.created_by_agent_id IS NOT NULL OR NEW.payload_version<>1 OR NEW.status='CONSUMED' OR
          NEW.project_id IS DISTINCT FROM source.project_id OR
          NEW.company_id IS DISTINCT FROM source.company_id OR
          NEW.source_draft_id IS DISTINCT FROM source.source_draft_id OR
          NEW.form_url IS DISTINCT FROM source.form_url OR
          NEW.subject IS DISTINCT FROM source.subject OR
          NEW.body IS DISTINCT FROM source.body OR NEW.sender IS DISTINCT FROM source.sender OR
          NEW.field_values IS DISTINCT FROM source.field_values OR
          NEW.expires_at > source.expires_at OR
          p->>'environment' IS DISTINCT FROM 'RESERVATION_ONLY' OR
          p->'execution_allowed' IS DISTINCT FROM 'false'::jsonb OR
          p->>'source_approval_hash' IS DISTINCT FROM source.payload_hash OR
          p->>'source_approval_version' IS DISTINCT FROM source.payload_version::text OR
          p->'input_packet' IS DISTINCT FROM source.payload_snapshot->'cf7_real_handoff' OR
          NEW.payload_snapshot->>'delivery_method' IS DISTINCT FROM NEW.delivery_method OR
          NEW.payload_snapshot->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
          NEW.payload_snapshot->>'company_id' IS DISTINCT FROM NEW.company_id::text OR
          NEW.payload_snapshot->>'source_draft_id' IS DISTINCT FROM NEW.source_draft_id::text THEN
          RAISE EXCEPTION 'CF7 reservation binding required' USING ERRCODE='23514';
        END IF;
        IF TG_OP='INSERT' AND (NEW.status <> 'PENDING' OR source.status <> 'APPROVED' OR
          source.expires_at <= now() OR NOT EXISTS (SELECT 1 FROM human_approval_proofs h
          WHERE h.request_id=source.id AND h.user_id=source.approved_by_user_id AND
          h.payload_hash=source.payload_hash AND h.payload_version=source.payload_version AND
          h.used_at IS NOT NULL AND h.verified_at IS NOT NULL)) THEN
          RAISE EXCEPTION 'Human candidate proof required' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_reservation_approval BEFORE INSERT OR UPDATE ON approval_requests
      FOR EACH ROW EXECUTE FUNCTION cf7_reservation_approval_guard();
    CREATE FUNCTION cf7_reservation_execution_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE p jsonb; a uuid; r approval_requests%ROWTYPE; marked boolean;
    BEGIN
      IF TG_TABLE_NAME='approved_form_dispatches' THEN
        p := NEW.payload_snapshot; a := NEW.approval_id;
        marked := cf7_reservation_marker(p);
        IF TG_OP='UPDATE' THEN
          marked := marked OR cf7_reservation_marker(OLD.payload_snapshot);
        END IF;
      ELSIF TG_TABLE_NAME='approved_email_reservations' THEN
        p := NEW.envelope; a := NEW.approval_id; marked := cf7_reservation_marker(p);
      ELSE
        p := NEW.execution_authorization; marked := cf7_reservation_marker(p);
        BEGIN a := (p->>'approval_id')::uuid;
        EXCEPTION WHEN invalid_text_representation THEN a := NULL; END;
      END IF;
      SELECT * INTO r FROM approval_requests WHERE id=a;
      IF marked OR r.delivery_method='cf7_real_reservation' THEN
        IF TG_TABLE_NAME <> 'approved_form_dispatches' THEN
          RAISE EXCEPTION 'CF7 reservation cannot authorize delivery' USING ERRCODE='23514';
        END IF;
        IF r.delivery_method IS DISTINCT FROM 'cf7_real_reservation' OR
          NEW.payload_snapshot IS DISTINCT FROM r.payload_snapshot OR
          NEW.payload_hash IS DISTINCT FROM r.payload_hash OR
          NEW.project_id IS DISTINCT FROM r.project_id OR
          NEW.company_id IS DISTINCT FROM r.company_id OR
          NEW.draft_id IS DISTINCT FROM r.source_draft_id OR
          NEW.form_url IS DISTINCT FROM r.form_url OR
          NEW.status NOT IN ('queued','blocked','cancelled') OR NEW.worker_id IS NOT NULL OR
          NEW.lease_expires_at IS NOT NULL OR
          NEW.started_at IS NOT NULL OR
          NEW.delivery_id IS NOT NULL THEN
          RAISE EXCEPTION 'CF7 reservation is non-executable' USING ERRCODE='23514';
        END IF;
        IF TG_OP='INSERT' AND (r.status <> 'APPROVED' OR r.expires_at <= now() OR
          NOT EXISTS (SELECT 1 FROM human_approval_proofs h WHERE h.request_id=r.id AND
          h.user_id=r.approved_by_user_id AND h.payload_hash=r.payload_hash AND
          h.payload_version=r.payload_version AND
          h.used_at IS NOT NULL AND
          h.verified_at IS NOT NULL)) THEN
          RAISE EXCEPTION 'Separate Human reservation proof required' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_reservation_form BEFORE INSERT OR UPDATE ON approved_form_dispatches
      FOR EACH ROW EXECUTE FUNCTION cf7_reservation_execution_guard();
    CREATE TRIGGER cf7_reservation_email BEFORE INSERT OR UPDATE ON approved_email_reservations
      FOR EACH ROW EXECUTE FUNCTION cf7_reservation_execution_guard();
    CREATE TRIGGER cf7_reservation_delivery BEFORE INSERT OR UPDATE ON form_deliveries
      FOR EACH ROW EXECUTE FUNCTION cf7_reservation_execution_guard();
    """)


def downgrade():
    op.execute("""
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM approval_requests WHERE delivery_method='cf7_real_reservation' OR
        cf7_reservation_marker(payload_snapshot)) THEN
        RAISE EXCEPTION 'CF7 reservation history prevents downgrade' USING ERRCODE='23514';
      END IF;
    END $$;
    DROP TRIGGER cf7_reservation_delivery ON form_deliveries;
    DROP TRIGGER cf7_reservation_email ON approved_email_reservations;
    DROP TRIGGER cf7_reservation_form ON approved_form_dispatches;
    DROP FUNCTION cf7_reservation_execution_guard();
    DROP TRIGGER cf7_reservation_approval ON approval_requests;
    DROP FUNCTION cf7_reservation_approval_guard();
    DROP FUNCTION cf7_reservation_marker(jsonb);
    """)
    op.drop_constraint("ck_cf7_reservation_not_started", "approved_form_dispatches", type_="check")
    op.drop_constraint("ck_cf7_reservation_not_consumed", "approval_requests", type_="check")
