"""O3-B diagnostic evidence; no observation execution or sending integration."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0263cd208659"
down_revision = "0152bc1f7548"
branch_labels = None
depends_on = None

OLD_TYPES = (
    "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
    "'form_intelligence', 'prepare_outreach')"
)
NEW_TYPES = OLD_TYPES[:-1] + ", 'cf7_observation')"


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint("ck_operation_job_type", "operation_jobs", NEW_TYPES)
    op.create_table(
        "form_observation_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "operation_job_id", sa.Uuid(), sa.ForeignKey("operation_jobs.id"), nullable=False
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_worker_id", sa.Uuid(), nullable=False),
        sa.Column("initiated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("canonical_snapshot", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "operation_job_id", "run_id", "attempt_number", name="uq_observation_attempt"
        ),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 1000", name="ck_observation_attempt"),
        sa.CheckConstraint("snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_observation_hash"),
        sa.CheckConstraint("octet_length(canonical_snapshot) <= 32768", name="ck_observation_size"),
        sa.CheckConstraint(
            "expires_at > observed_at AND expires_at <= observed_at + interval '24 hours'",
            name="ck_observation_expiry",
        ),
    )
    op.create_table(
        "form_observation_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "operation_job_id", sa.Uuid(), sa.ForeignKey("operation_jobs.id"), nullable=False
        ),
        sa.Column(
            "evidence_id", sa.Uuid(), sa.ForeignKey("form_observation_evidence.id"), nullable=False
        ),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("principal_type", sa.String(10), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(30), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('SAVED','RETIRED')", name="ck_observation_event_type"),
        sa.CheckConstraint(
            "principal_type IN ('HUMAN','SYSTEM')", name="ck_observation_event_principal"
        ),
        sa.CheckConstraint(
            "reason_code IN ('EVIDENCE_SAVED','HUMAN_RETIRED')", name="ck_observation_event_reason"
        ),
    )
    for table, names in (
        ("form_observation_evidence", ("project_id", "company_id", "operation_job_id")),
        (
            "form_observation_events",
            ("project_id", "company_id", "operation_job_id", "evidence_id"),
        ),
    ):
        for name in names:
            op.create_index("ix_" + table + "_" + name, table, [name])
    op.create_index(
        "uq_observation_saved_event",
        "form_observation_events",
        ["evidence_id"],
        unique=True,
        postgresql_where=sa.text("event_type = 'SAVED'"),
    )
    op.execute(SQL)


SQL = r"""
CREATE FUNCTION form_observation_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Observation records are append only' USING ERRCODE='23514'; END $$;
CREATE TRIGGER observation_evidence_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON form_observation_evidence FOR EACH STATEMENT EXECUTE FUNCTION form_observation_immutable();
CREATE TRIGGER observation_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON form_observation_events FOR EACH STATEMENT EXECUTE FUNCTION form_observation_immutable();

CREATE FUNCTION form_observation_source(cid uuid) RETURNS text LANGUAGE sql STABLE AS $$
SELECT encode(sha256(convert_to(jsonb_build_array(c.project_id::text,c.id::text,
  c.website_url,c.contact_url)::text,'UTF8')),'hex') FROM companies c WHERE c.id=cid $$;

CREATE FUNCTION form_observation_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE c companies; j operation_jobs; p projects; s jsonb; b jsonb; f jsonb; v jsonb;
  keys text[]; ck text[];
BEGIN
  IF current_database() !~ '_test$' THEN
    RAISE EXCEPTION 'Observation storage requires test database' USING ERRCODE='23514';
  END IF;
  SELECT * INTO j FROM operation_jobs WHERE id=NEW.operation_job_id FOR UPDATE;
  SELECT * INTO c FROM companies WHERE id=NEW.company_id FOR UPDATE;
  SELECT * INTO p FROM projects WHERE id=NEW.project_id FOR UPDATE;
  PERFORM 1 FROM project_members WHERE project_id=NEW.project_id
    AND user_id=NEW.initiated_by_user_id FOR SHARE;
  IF c.id IS NULL OR j.id IS NULL OR p.id IS NULL OR c.project_id<>p.id OR j.project_id<>p.id
    OR j.operation_type<>'cf7_observation' OR j.status<>'running' OR j.cancel_requested
    OR j.lease_expires_at IS NULL OR j.lease_expires_at<=clock_timestamp()
    OR j.worker_id IS DISTINCT FROM NEW.lease_worker_id OR j.attempt_count<>NEW.attempt_number
    OR c.contact_url<>'https://managed.example/contact/'
    OR j.payload->>'company_id' IS DISTINCT FROM c.id::text
    OR j.payload->>'run_id' IS DISTINCT FROM NEW.run_id::text
    OR j.payload->>'initiated_by_user_id' IS DISTINCT FROM NEW.initiated_by_user_id::text
    OR (p.user_id<>NEW.initiated_by_user_id AND NOT EXISTS
      (SELECT 1 FROM project_members WHERE project_id=p.id
        AND user_id=NEW.initiated_by_user_id AND role='editor'))
  THEN RAISE EXCEPTION 'Observation current binding denied' USING ERRCODE='23514'; END IF;
  s:=NEW.snapshot; b:=s->'binding'; f:=s->'fetch_summary';
  keys:=ARRAY['evidence_id','binding','source_kind','provenance','observer_version',
    'fetch_policy_version','snapshot_schema_version','redaction_version','started_at',
    'observed_at','expires_at','decision','reason_code','sales_permission','captcha_state',
    'eligible_for_approval','execution_allowed','body_sha256','parser_evidence_hash',
    'robots_sha256','fetch_summary','structure_summary'];
  IF NOT s ?& keys OR s-keys<>'{}'::jsonb OR jsonb_typeof(s)<>'object'
    OR jsonb_path_exists(s-'structure_summary', '$.** ? (@ == null)')
    OR NEW.canonical_snapshot::jsonb IS DISTINCT FROM s
    OR encode(sha256(convert_to(NEW.canonical_snapshot,'UTF8')),'hex')<>NEW.snapshot_hash
    OR s->>'evidence_id' IS DISTINCT FROM NEW.id::text
    OR (s->>'observed_at')::timestamptz IS DISTINCT FROM NEW.observed_at
    OR (s->>'expires_at')::timestamptz IS DISTINCT FROM NEW.expires_at
    OR NEW.observed_at>clock_timestamp() OR NEW.expires_at<=clock_timestamp()
    OR (s->>'started_at')::timestamptz>NEW.observed_at
    OR NEW.observed_at-(s->>'started_at')::timestamptz>interval '30 seconds'
    OR s->'eligible_for_approval' IS DISTINCT FROM 'false'::jsonb
    OR s->'execution_allowed' IS DISTINCT FROM 'false'::jsonb
    OR s->>'source_kind'<>'STATIC_HTML_UNVERIFIED' OR s->>'provenance'<>'OWNED_TLS_FIXTURE'
    OR s->>'observer_version'<>'cf7-static-observer-lab-v1'
    OR s->>'fetch_policy_version'<>'owned-get-lab-v1'
    OR s->>'snapshot_schema_version'<>'observation-storage-v1'
    OR s->>'redaction_version'<>'diagnostic-projection-v1'
    OR s->>'sales_permission' NOT IN ('UNCERTAIN','PROHIBITED')
    OR s->>'captcha_state' NOT IN ('UNVERIFIED','DETECTED')
    OR NOT (s->>'body_sha256' ~ '^[0-9a-f]{64}$' AND s->>'parser_evidence_hash' ~ '^[0-9a-f]{64}$'
      AND s->>'robots_sha256' ~ '^[0-9a-f]{64}$')
  THEN RAISE EXCEPTION 'Observation snapshot denied' USING ERRCODE='23514'; END IF;
  keys:=ARRAY['project_id','company_id','company_project_id','operation_job_id','job_project_id',
    'run_id','lease_worker_id','initiated_by_user_id','attempt_number','operation_type','target_url','company_source_hash'];
  IF NOT b ?& keys OR b-keys<>'{}'::jsonb OR jsonb_typeof(b)<>'object'
    OR b->>'project_id' IS DISTINCT FROM p.id::text
    OR b->>'company_project_id' IS DISTINCT FROM p.id::text
    OR b->>'job_project_id' IS DISTINCT FROM p.id::text
    OR b->>'company_id' IS DISTINCT FROM c.id::text
    OR b->>'operation_job_id' IS DISTINCT FROM j.id::text
    OR b->>'run_id' IS DISTINCT FROM NEW.run_id::text
    OR b->>'lease_worker_id' IS DISTINCT FROM NEW.lease_worker_id::text
    OR b->>'initiated_by_user_id' IS DISTINCT FROM NEW.initiated_by_user_id::text
    OR b->'attempt_number' IS DISTINCT FROM to_jsonb(NEW.attempt_number)
    OR b->>'operation_type'<>'cf7_observation' OR b->>'target_url' IS DISTINCT FROM c.contact_url
    OR b->>'company_source_hash' IS DISTINCT FROM form_observation_source(c.id)
  THEN RAISE EXCEPTION 'Observation source mismatch' USING ERRCODE='23514'; END IF;
  keys:=ARRAY['status','media_type','body_bytes','robots_bytes','robots_decision',
    'tls_identity_verified','pinned_ips','duration_ms'];
  IF NOT f ?& keys OR f-keys<>'{}'::jsonb OR jsonb_typeof(f)<>'object'
    OR f->'status' IS DISTINCT FROM '200'::jsonb
    OR f->>'media_type' NOT IN ('text/html','text/html; charset=utf-8')
    OR (f->>'body_bytes')::integer NOT BETWEEN 1 AND 65536
    OR (f->>'robots_bytes')::integer NOT BETWEEN 1 AND 16384
    OR f->>'robots_decision'<>'ALLOWED_OWNED_FIXTURE'
    OR f->'tls_identity_verified' IS DISTINCT FROM 'true'::jsonb
    OR jsonb_typeof(f->'pinned_ips')<>'array' OR jsonb_array_length(f->'pinned_ips')<>2
    OR (f->>'duration_ms')::integer IS DISTINCT FROM
      trunc(extract(epoch FROM NEW.observed_at-(s->>'started_at')::timestamptz)*1000)::integer
  THEN RAISE EXCEPTION 'Observation fetch summary denied' USING ERRCODE='23514'; END IF;
  -- Lab IPs are synthetic validation values, never real connection destinations.
  IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(f->'pinned_ips') ip
      WHERE ip NOT IN ('8.8.8.8','1.1.1.1')) THEN
    RAISE EXCEPTION 'Observation fixture IP denied' USING ERRCODE='23514'; END IF;
  IF s->>'decision'='REVIEW_REQUIRED' THEN
    v:=s->'structure_summary'; keys:=ARRAY['form_count','cf7_version','mapping','controls'];
    IF jsonb_typeof(v)<>'object' OR jsonb_path_exists(v, '$.** ? (@ == null)')
      OR s->>'reason_code'<>'STATIC_ONLY_UNVERIFIED' OR NOT v ?& keys OR v-keys<>'{}'::jsonb
      OR v->'form_count' IS DISTINCT FROM '1'::jsonb OR v->>'cf7_version'<>'6.1.4'
      OR v->>'mapping'<>'HUMAN_REQUIRED' OR jsonb_typeof(v->'controls')<>'array'
      OR jsonb_array_length(v->'controls') NOT BETWEEN 3 AND 50 THEN
      RAISE EXCEPTION 'Observation structure denied' USING ERRCODE='23514'; END IF;
    ck:=ARRAY['position','name','label','kind','required','default_checked','redacted','truncated'];
    FOR f IN SELECT value FROM jsonb_array_elements(v->'controls') LOOP
      IF NOT f ?& ck OR f-ck<>'{}'::jsonb OR jsonb_typeof(f)<>'object'
        OR jsonb_typeof(f->'name')<>'string' OR length(f->>'name')>100
        OR jsonb_typeof(f->'label')<>'string' OR length(f->>'label')>250
        OR f->>'kind' NOT IN ('text','email','tel','textarea','checkbox')
        OR jsonb_typeof(f->'required')<>'boolean' OR jsonb_typeof(f->'default_checked')<>'boolean'
        OR jsonb_typeof(f->'redacted')<>'boolean' OR jsonb_typeof(f->'truncated')<>'boolean'
        OR ((f->>'name')||' '||(f->>'label')) ~*
          ('(secret|password|api[-_ ]?key|bearer|authorization|cookie|token|smtp|sk-proj-|'
           || '[[:alnum:].+-]+@[[:alnum:].-]+\.[a-z]{2,})')
      THEN RAISE EXCEPTION 'Observation projection denied' USING ERRCODE='23514'; END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(v->'controls') WITH ORDINALITY x(value,n)
      WHERE value->'position' IS DISTINCT FROM to_jsonb((n-1)::integer)) THEN
      RAISE EXCEPTION 'Observation positions denied' USING ERRCODE='23514'; END IF;
  ELSE
    IF s->'structure_summary' IS DISTINCT FROM 'null'::jsonb OR NOT (
      (s->>'decision'='BLOCKED' AND s->>'reason_code'='SALES_PROHIBITED') OR
      (s->>'decision'='HUMAN_REQUIRED' AND s->>'reason_code' IN
       ('CAPTCHA_DETECTED','BASE_URL_OVERRIDE','CUSTOM_EXECUTION','EXTERNAL_FORM_CONTROLS',
        'FORM_ACTION','CONTROL_STATE','LABEL_UNVERIFIED','ACCEPTANCE_UNSUPPORTED')) OR
      (s->>'decision'='UNSUPPORTED' AND s->>'reason_code' IN
       ('PAGE_URL_POLICY','HTTP_METADATA','BODY_BOUNDS',
       'HTML_ENCODING_OR_ATTRIBUTES','HTML_CHARSET','DUPLICATE_IDS','FORM_COUNT_OR_TYPE','FORM_METHOD',
       'STATIC_CONFIG_OR_ROOT','UNNAMED_CONTROL','FIELD_NAMES_OR_LIMIT','HIDDEN_OR_TOKEN',
       'VERSION_OR_ID_BINDING','CONTROL_TYPE_OR_NAME','CHECKBOX_VALUE','CONTROL_COUNT'))
    ) THEN RAISE EXCEPTION 'Observation decision denied' USING ERRCODE='23514'; END IF;
  END IF;
  IF s->>'sales_permission' IS DISTINCT FROM
      (CASE WHEN s->>'decision'='BLOCKED' THEN 'PROHIBITED' ELSE 'UNCERTAIN' END)
    OR s->>'captcha_state' IS DISTINCT FROM
      (CASE WHEN s->>'reason_code'='CAPTCHA_DETECTED' THEN 'DETECTED' ELSE 'UNVERIFIED' END)
  THEN RAISE EXCEPTION 'Observation state denied' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER observation_binding_guard BEFORE INSERT ON form_observation_evidence
FOR EACH ROW EXECUTE FUNCTION form_observation_binding();

CREATE FUNCTION form_observation_event_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e form_observation_evidence; p projects;
BEGIN
  SELECT * INTO e FROM form_observation_evidence WHERE id=NEW.evidence_id;
  SELECT * INTO p FROM projects WHERE id=NEW.project_id FOR UPDATE;
  PERFORM 1 FROM project_members WHERE project_id=NEW.project_id
    AND user_id=NEW.actor_user_id FOR SHARE;
  IF e.id IS NULL OR e.project_id<>NEW.project_id OR e.company_id<>NEW.company_id
    OR e.operation_job_id<>NEW.operation_job_id OR e.snapshot_hash<>NEW.snapshot_hash
    OR NEW.created_at>clock_timestamp()
    OR (p.user_id<>NEW.actor_user_id AND NOT EXISTS (SELECT 1 FROM project_members
      WHERE project_id=p.id AND user_id=NEW.actor_user_id AND role='editor'))
    OR (NEW.event_type='SAVED' AND (NEW.principal_type<>'SYSTEM'
      OR NEW.actor_user_id<>e.initiated_by_user_id OR NEW.reason_code<>'EVIDENCE_SAVED'))
    OR (NEW.event_type='RETIRED' AND
      (NEW.principal_type<>'HUMAN' OR NEW.reason_code<>'HUMAN_RETIRED'))
  THEN RAISE EXCEPTION 'Observation event binding denied' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER observation_event_binding_guard BEFORE INSERT ON form_observation_events
FOR EACH ROW EXECUTE FUNCTION form_observation_event_binding();

CREATE FUNCTION form_observation_saved_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (SELECT count(*) FROM form_observation_events
      WHERE evidence_id=NEW.id AND event_type='SAVED')<>1
    OR NOT EXISTS (SELECT 1 FROM operation_jobs WHERE id=NEW.operation_job_id
      AND status='completed' AND processed_count=1 AND success_count=1 AND failed_count=0)
  THEN RAISE EXCEPTION 'Observation result requires ledger and job completion'
    USING ERRCODE='23514'; END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER observation_saved_atomic AFTER INSERT ON form_observation_evidence
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION form_observation_saved_guard();

CREATE FUNCTION form_observation_parent_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='companies' THEN
    IF NEW.project_id IS DISTINCT FROM OLD.project_id AND EXISTS
      (SELECT 1 FROM form_observation_evidence WHERE company_id=OLD.id) THEN
      RAISE EXCEPTION 'Observation company cannot move project' USING ERRCODE='23514'; END IF;
  ELSE
    IF EXISTS (SELECT 1 FROM form_observation_evidence WHERE operation_job_id=OLD.id)
      AND (NEW.status<>'completed' OR NEW.processed_count<>1 OR NEW.success_count<>1
        OR NEW.failed_count<>0 OR NEW.worker_id IS NOT NULL
        OR NEW.lease_expires_at IS NOT NULL) THEN
      RAISE EXCEPTION 'Observation completed job is immutable' USING ERRCODE='23514'; END IF;
    IF (NEW.project_id IS DISTINCT FROM OLD.project_id
      OR NEW.operation_type IS DISTINCT FROM OLD.operation_type
      OR NEW.payload IS DISTINCT FROM OLD.payload) AND EXISTS
      (SELECT 1 FROM form_observation_evidence WHERE operation_job_id=OLD.id) THEN
      RAISE EXCEPTION 'Observation job binding is immutable' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER observation_company_parent BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION form_observation_parent_guard();
CREATE TRIGGER observation_job_parent BEFORE UPDATE ON operation_jobs
FOR EACH ROW EXECUTE FUNCTION form_observation_parent_guard();
"""


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM form_observation_evidence)
        OR EXISTS (SELECT 1 FROM form_observation_events)
        OR EXISTS (SELECT 1 FROM operation_jobs WHERE operation_type='cf7_observation') THEN
        RAISE EXCEPTION 'Observation records exist; downgrade forbidden' USING ERRCODE='23514';
      END IF;
    END $$;
    DROP FUNCTION form_observation_parent_guard() CASCADE;
    DROP FUNCTION form_observation_saved_guard() CASCADE;
    DROP FUNCTION form_observation_event_binding() CASCADE;
    DROP FUNCTION form_observation_binding() CASCADE;
    DROP FUNCTION form_observation_source(uuid);
    DROP FUNCTION form_observation_immutable() CASCADE;""")
    op.drop_table("form_observation_events")
    op.drop_table("form_observation_evidence")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint("ck_operation_job_type", "operation_jobs", OLD_TYPES)
