"""A2 Human Approval Foundation (no dispatch)."""

from alembic import op

revision = "a2f0c6d8e913"
down_revision = "c1d9f6a2b4e8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE agent_identities (
        id UUID NOT NULL,
        name VARCHAR(200) NOT NULL,
        active BOOLEAN NOT NULL,
        created_by_user_id UUID NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id)
    )
    """)
    op.execute("""
    CREATE TABLE agent_credentials (
        id UUID NOT NULL,
        agent_id UUID NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        scopes JSONB NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        revoked BOOLEAN NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(agent_id) REFERENCES agent_identities (id),
        UNIQUE (token_hash)
    )
    """)
    op.execute("CREATE INDEX ix_agent_credentials_agent_id ON agent_credentials (agent_id)")
    op.execute("""
    CREATE TABLE agent_project_grants (
        id UUID NOT NULL,
        agent_id UUID NOT NULL,
        project_id UUID NOT NULL,
        scopes JSONB NOT NULL,
        active BOOLEAN NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_agent_project_grant UNIQUE (agent_id, project_id),
        FOREIGN KEY(agent_id) REFERENCES agent_identities (id),
        FOREIGN KEY(project_id) REFERENCES projects (id)
    )
    """)
    op.execute(
        "CREATE INDEX ix_agent_project_grants_project_id ON agent_project_grants (project_id)"
    )
    op.execute("""
    CREATE TABLE approval_requests (
        id UUID NOT NULL,
        project_id UUID NOT NULL,
        company_id UUID NOT NULL,
        channel VARCHAR(20) NOT NULL,
        delivery_method VARCHAR(30) NOT NULL,
        source_draft_id UUID,
        recipient VARCHAR(320),
        form_url TEXT,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        sender JSONB NOT NULL,
        field_values JSONB NOT NULL,
        payload_snapshot JSONB NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        payload_version INTEGER NOT NULL,
        canonicalization_version VARCHAR(30) NOT NULL,
        proposal_id UUID NOT NULL,
        supersedes_request_id UUID,
        created_by_principal_type VARCHAR(10) NOT NULL,
        created_by_agent_id UUID,
        created_by_user_id UUID,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        status VARCHAR(20) NOT NULL,
        approved_by_user_id UUID,
        approved_at TIMESTAMP WITH TIME ZONE,
        approved_payload_hash VARCHAR(64),
        approved_payload_version INTEGER,
        rejection_reason TEXT,
        invalidation_reason TEXT,
        PRIMARY KEY (id),
        CONSTRAINT ck_approval_status
        CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED','REVOKED','CONSUMED')),
        CONSTRAINT ck_approval_channel CHECK (channel IN ('email','form')),
        CONSTRAINT ck_approval_creator CHECK (created_by_principal_type IN ('HUMAN','AGENT')),
        CONSTRAINT ck_approval_version CHECK (payload_version > 0),
        CONSTRAINT ck_approval_expiry
        CHECK (expires_at > created_at AND expires_at <= created_at + interval '24 hours'),
        CONSTRAINT uq_approval_proposal_version UNIQUE (proposal_id, payload_version),
        FOREIGN KEY(project_id) REFERENCES projects (id),
        FOREIGN KEY(company_id) REFERENCES companies (id),
        FOREIGN KEY(source_draft_id) REFERENCES outreach_drafts (id),
        UNIQUE (supersedes_request_id),
        FOREIGN KEY(supersedes_request_id) REFERENCES approval_requests (id),
        FOREIGN KEY(created_by_agent_id) REFERENCES agent_identities (id),
        FOREIGN KEY(created_by_user_id) REFERENCES users (id),
        FOREIGN KEY(approved_by_user_id) REFERENCES users (id)
    )
    """)
    op.execute("CREATE INDEX ix_approval_requests_company_id ON approval_requests (company_id)")
    op.execute("CREATE INDEX ix_approval_requests_project_id ON approval_requests (project_id)")
    op.execute("""
    CREATE TABLE human_approval_proofs (
        id UUID NOT NULL,
        request_id UUID NOT NULL,
        user_id UUID NOT NULL,
        session_hash VARCHAR(64) NOT NULL,
        payload_hash VARCHAR(64) NOT NULL,
        payload_version INTEGER NOT NULL,
        action VARCHAR(20) NOT NULL,
        token_hash VARCHAR(64) NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        verified_at TIMESTAMP WITH TIME ZONE,
        used_at TIMESTAMP WITH TIME ZONE,
        method VARCHAR(30) NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(request_id) REFERENCES approval_requests (id),
        FOREIGN KEY(user_id) REFERENCES users (id),
        UNIQUE (token_hash)
    )
    """)
    op.execute(
        "CREATE INDEX ix_human_approval_proofs_request_id ON human_approval_proofs (request_id)"
    )
    op.execute("""
    CREATE TABLE outreach_audit_events (
        id UUID NOT NULL,
        event VARCHAR(60) NOT NULL,
        principal_type VARCHAR(10) NOT NULL,
        actor_id UUID,
        request_id UUID,
        project_id UUID,
        company_id UUID,
        payload_hash VARCHAR(64),
        payload_version INTEGER,
        before_status VARCHAR(20),
        after_status VARCHAR(20),
        timestamp TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        reason VARCHAR(200),
        PRIMARY KEY (id),
        FOREIGN KEY(request_id) REFERENCES approval_requests (id),
        FOREIGN KEY(project_id) REFERENCES projects (id),
        FOREIGN KEY(company_id) REFERENCES companies (id)
    )
    """)
    op.execute(
        "CREATE INDEX ix_outreach_audit_events_project_id ON outreach_audit_events (project_id)"
    )
    op.execute(
        "CREATE INDEX ix_outreach_audit_events_request_id ON outreach_audit_events (request_id)"
    )

    op.execute("""
        CREATE FUNCTION a2_append_only_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Outreach audit ledger is append-only' USING ERRCODE = '23514';
        END $$;
        CREATE TRIGGER a2_ledger_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
        ON outreach_audit_events FOR EACH STATEMENT EXECUTE FUNCTION a2_append_only_ledger();
    """)
    op.execute("""
        CREATE FUNCTION a2_immutable_approval() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Approval requests cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['status','approved_by_user_id','approved_at',
                    'approved_payload_hash','approved_payload_version','rejection_reason',
                    'invalidation_reason']) IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status','approved_by_user_id','approved_at',
                    'approved_payload_hash','approved_payload_version','rejection_reason',
                    'invalidation_reason']) THEN
                RAISE EXCEPTION 'Approval payload is immutable; create a revision'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.status <> NEW.status AND NOT (
                (OLD.status = 'PENDING' AND NEW.status IN
                    ('APPROVED','REJECTED','EXPIRED','REVOKED')) OR
                (OLD.status = 'APPROVED' AND NEW.status IN ('EXPIRED','REVOKED'))
            ) THEN
                RAISE EXCEPTION 'Illegal A2 approval transition' USING ERRCODE = '23514';
            END IF;
            IF OLD.approved_at IS NOT NULL AND ROW(NEW.approved_by_user_id,NEW.approved_at,
                NEW.approved_payload_hash,NEW.approved_payload_version) IS DISTINCT FROM
                ROW(OLD.approved_by_user_id,OLD.approved_at,
                OLD.approved_payload_hash,OLD.approved_payload_version) THEN
                RAISE EXCEPTION 'Approval proof is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.status = 'APPROVED' AND (NEW.approved_by_user_id IS NULL OR
                NEW.approved_at IS NULL OR NEW.approved_payload_hash IS DISTINCT FROM
                NEW.payload_hash OR NEW.approved_payload_version IS DISTINCT FROM
                NEW.payload_version) THEN
                RAISE EXCEPTION 'Approval binding required' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER a2_approval_immutable BEFORE UPDATE OR DELETE
        ON approval_requests FOR EACH ROW EXECUTE FUNCTION a2_immutable_approval();
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS a2_immutable_approval() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS a2_append_only_ledger() CASCADE")
    op.drop_table("outreach_audit_events")
    op.drop_table("human_approval_proofs")
    op.drop_table("approval_requests")
    op.drop_table("agent_project_grants")
    op.drop_table("agent_credentials")
    op.drop_table("agent_identities")
