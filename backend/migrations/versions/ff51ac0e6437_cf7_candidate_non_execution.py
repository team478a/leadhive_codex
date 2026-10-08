"""P1: permanently non-executable CF7 candidates, without publishing preparation APIs."""

from alembic import op

revision = "ff51ac0e6437"
down_revision = "fe409dbf5326"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_cf7_candidate_not_consumed",
        "approval_requests",
        "delivery_method <> 'cf7_candidate_only' OR status <> 'CONSUMED'",
    )
    op.execute("""
    CREATE FUNCTION cf7_candidate_marker(p jsonb) RETURNS boolean
    LANGUAGE sql IMMUTABLE AS $$
      SELECT COALESCE(p->>'delivery_method'='cf7_candidate_only',false)
        OR COALESCE(p ? 'cf7_candidate_snapshot',false)
        OR COALESCE(p ? 'cf7_candidate_snapshot_hash',false);
    $$;

    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM approval_requests WHERE
          delivery_method='cf7_candidate_only' OR cf7_candidate_marker(payload_snapshot)) THEN
        RAISE EXCEPTION 'Unprotected CF7 candidate evidence exists; upgrade stopped'
          USING ERRCODE='23514';
      END IF;
    END $$;

    CREATE FUNCTION cf7_candidate_approval_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE s jsonb; c jsonb;
    BEGIN
      IF NEW.delivery_method='cf7_candidate_only' OR
         cf7_candidate_marker(NEW.payload_snapshot) THEN
        s := NEW.payload_snapshot->'cf7_candidate_snapshot';
        c := s->'contract';
        IF NEW.status='CONSUMED' THEN
          RAISE EXCEPTION 'CF7 candidate cannot be consumed'
            USING ERRCODE='23514', CONSTRAINT='ck_cf7_candidate_not_consumed';
        END IF;
        IF NEW.delivery_method IS DISTINCT FROM 'cf7_candidate_only' OR
           NEW.channel IS DISTINCT FROM 'form' OR NEW.recipient IS NOT NULL OR
           NEW.source_draft_id IS NULL OR NEW.form_url IS NULL OR
           NEW.canonicalization_version IS DISTINCT FROM 'json-v1' OR
           jsonb_typeof(NEW.payload_snapshot) IS DISTINCT FROM 'object' OR
           jsonb_typeof(s) IS DISTINCT FROM 'object' OR
           jsonb_typeof(c) IS DISTINCT FROM 'object' OR
           NEW.payload_snapshot->>'delivery_method' IS DISTINCT FROM NEW.delivery_method OR
           NEW.payload_snapshot->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
           NEW.payload_snapshot->>'company_id' IS DISTINCT FROM NEW.company_id::text OR
           NEW.payload_snapshot->>'source_draft_id' IS DISTINCT FROM NEW.source_draft_id::text OR
           NEW.payload_snapshot->'payload_version' IS DISTINCT FROM to_jsonb(NEW.payload_version) OR
           c->>'environment' IS DISTINCT FROM 'NON_EXECUTABLE' OR
           c->>'delivery_method' IS DISTINCT FROM 'cf7_candidate_only' OR
           c->>'contract_version' IS DISTINCT FROM 'cf7-candidate-v1' OR
           c->>'canonicalization_version' IS DISTINCT FROM 'cf7-candidate-json-v1' OR
           c->>'encoding_version' IS DISTINCT FROM 'browser-crlf-utf8-v1' OR
           c->>'project_id' IS DISTINCT FROM NEW.project_id::text OR
           c->>'company_id' IS DISTINCT FROM NEW.company_id::text OR
           c->>'source_draft_id' IS DISTINCT FROM NEW.source_draft_id::text OR
           c->'payload_version' IS DISTINCT FROM to_jsonb(NEW.payload_version) OR
           c->>'form_url' IS DISTINCT FROM NEW.form_url OR
           c->>'subject' IS DISTINCT FROM NEW.subject OR
           c->>'body' IS DISTINCT FROM NEW.body OR
           jsonb_typeof(c->'hidden') IS DISTINCT FROM 'array' OR
           jsonb_typeof(c->'controls') IS DISTINCT FROM 'array' OR
           jsonb_typeof(c->'field_values') IS DISTINCT FROM 'array' OR
           jsonb_typeof(c->'sender') IS DISTINCT FROM 'array' OR
           jsonb_typeof(c->'selections') IS DISTINCT FROM 'array' OR
           jsonb_typeof(s->'contract_hash') IS DISTINCT FROM 'string' OR
           jsonb_typeof(s->'wire_sha256') IS DISTINCT FROM 'string' OR
           jsonb_typeof(NEW.payload_snapshot->'cf7_candidate_snapshot_hash')
             IS DISTINCT FROM 'string' OR
           COALESCE(s->>'contract_hash' ~ '^[a-f0-9]{64}$',false) IS NOT TRUE OR
           COALESCE(s->>'wire_sha256' ~ '^[a-f0-9]{64}$',false) IS NOT TRUE OR
           COALESCE(NEW.payload_snapshot->>'cf7_candidate_snapshot_hash'
             ~ '^[a-f0-9]{64}$',false) IS NOT TRUE OR
           jsonb_typeof(s->'content_type') IS DISTINCT FROM 'string' OR
           jsonb_typeof(s->'wire_size') IS DISTINCT FROM 'number' OR
           (s->'wire_size' > '0'::jsonb AND s->'wire_size' <= '65536'::jsonb) IS NOT TRUE OR
           NOT EXISTS (SELECT 1 FROM companies co JOIN outreach_drafts d ON
             d.company_id=co.id JOIN form_profiles f ON f.company_id=co.id
             WHERE co.id=NEW.company_id AND co.project_id=NEW.project_id
               AND d.id=NEW.source_draft_id AND d.channel='form'
               AND f.id::text=c->>'form_profile_id') THEN
          RAISE EXCEPTION 'CF7 candidate binding required'
            USING ERRCODE='23514', CONSTRAINT='ck_cf7_candidate_binding';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_candidate_approval BEFORE INSERT OR UPDATE ON approval_requests
      FOR EACH ROW EXECUTE FUNCTION cf7_candidate_approval_guard();

    CREATE FUNCTION cf7_candidate_execution_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE p jsonb; a uuid;
    BEGIN
      IF TG_TABLE_NAME='approved_form_dispatches' THEN
        p := NEW.payload_snapshot; a := NEW.approval_id;
      ELSIF TG_TABLE_NAME='approved_email_reservations' THEN
        p := NEW.envelope; a := NEW.approval_id;
      ELSE
        p := NEW.execution_authorization;
        BEGIN
          a := (p->>'approval_id')::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
          a := NULL;
        END;
      END IF;
      IF cf7_candidate_marker(p) OR EXISTS (SELECT 1 FROM approval_requests r
          WHERE r.id=a AND (r.delivery_method='cf7_candidate_only' OR
            cf7_candidate_marker(r.payload_snapshot))) THEN
        RAISE EXCEPTION 'CF7 candidate cannot authorize execution'
          USING ERRCODE='23514', CONSTRAINT='ck_cf7_candidate_no_execution';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_candidate_form_reservation BEFORE INSERT OR UPDATE
      ON approved_form_dispatches FOR EACH ROW
      EXECUTE FUNCTION cf7_candidate_execution_guard();
    CREATE TRIGGER cf7_candidate_email_reservation BEFORE INSERT OR UPDATE
      ON approved_email_reservations FOR EACH ROW
      EXECUTE FUNCTION cf7_candidate_execution_guard();
    CREATE TRIGGER cf7_candidate_delivery BEFORE INSERT OR UPDATE
      ON form_deliveries FOR EACH ROW EXECUTE FUNCTION cf7_candidate_execution_guard();
    """)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM approval_requests WHERE
          delivery_method='cf7_candidate_only' OR cf7_candidate_marker(payload_snapshot)) THEN
        RAISE EXCEPTION 'CF7 candidate evidence exists; downgrade forbidden'
          USING ERRCODE='23514';
      END IF;
    END $$;
    DROP TRIGGER cf7_candidate_delivery ON form_deliveries;
    DROP TRIGGER cf7_candidate_email_reservation ON approved_email_reservations;
    DROP TRIGGER cf7_candidate_form_reservation ON approved_form_dispatches;
    DROP FUNCTION cf7_candidate_execution_guard();
    DROP TRIGGER cf7_candidate_approval ON approval_requests;
    DROP FUNCTION cf7_candidate_approval_guard();
    DROP FUNCTION cf7_candidate_marker(jsonb);
    """)
    op.drop_constraint("ck_cf7_candidate_not_consumed", "approval_requests", type_="check")
