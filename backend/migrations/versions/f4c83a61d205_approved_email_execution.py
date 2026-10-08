"""Human approved email reservations and conservative SMTP evidence."""

from alembic import op

revision = "f4c83a61d205"
down_revision = "e3b7d92f410a"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """

CREATE TABLE bulk_approval_proofs (
	id UUID NOT NULL,
	project_id UUID NOT NULL,
	user_id UUID NOT NULL,
	session_hash VARCHAR(64) NOT NULL,
	token_hash VARCHAR(64) NOT NULL,
	items JSONB NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	verified_at TIMESTAMP WITH TIME ZONE,
	used_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	UNIQUE (token_hash)
)

    """
    )
    op.execute(
        "CREATE INDEX ix_bulk_approval_proofs_project_id ON bulk_approval_proofs (project_id)"
    )
    op.execute(
        """

CREATE TABLE approved_email_batches (
	id UUID NOT NULL,
	project_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	name VARCHAR(200) NOT NULL,
	status VARCHAR(20) NOT NULL,
	daily_limit INTEGER NOT NULL,
	hourly_limit INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
        CONSTRAINT ck_approved_batch_status CHECK (status IN
('queued','paused','completed','cancelled')),
        CONSTRAINT ck_approved_batch_limits CHECK (daily_limit BETWEEN 1 AND 10000 AND
hourly_limit BETWEEN 1 AND 1000),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id),
	UNIQUE (idempotency_key)
)

    """
    )
    op.execute(
        "CREATE INDEX ix_approved_email_batches_project_id ON approved_email_batches (project_id)"
    )
    op.execute(
        """

CREATE TABLE approved_email_reservations (
	id UUID NOT NULL,
	batch_id UUID NOT NULL,
	approval_id UUID NOT NULL,
	delivery_id UUID NOT NULL,
	envelope JSONB NOT NULL,
	envelope_hash VARCHAR(64) NOT NULL,
	sender_email VARCHAR(320) NOT NULL,
	recipient_email VARCHAR(320) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(batch_id) REFERENCES approved_email_batches (id),
	UNIQUE (approval_id),
	FOREIGN KEY(approval_id) REFERENCES approval_requests (id),
	UNIQUE (delivery_id),
	FOREIGN KEY(delivery_id) REFERENCES email_deliveries (id)
)

    """
    )
    op.execute(
        """
CREATE INDEX ix_approved_email_reservations_recipient_email ON approved_email_reservations
(recipient_email)
    """
    )
    op.execute(
        """
CREATE INDEX ix_approved_email_reservations_sender_email ON approved_email_reservations
(sender_email)
    """
    )
    op.execute(
        "CREATE INDEX ix_approved_email_reservations_batch_id "
        "ON approved_email_reservations (batch_id)"
    )
    op.execute(
        """

CREATE TABLE email_send_attempts (
	id UUID NOT NULL,
	reservation_id UUID NOT NULL,
	payload_hash VARCHAR(64) NOT NULL,
	payload_version INTEGER NOT NULL,
	message_id VARCHAR(400) NOT NULL,
	result VARCHAR(20) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	finished_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
        CONSTRAINT ck_email_attempt_result CHECK (result IN
('STARTED','SMTP_ACCEPTED','FAILED','UNKNOWN')),
	UNIQUE (reservation_id),
	FOREIGN KEY(reservation_id) REFERENCES approved_email_reservations (id),
	UNIQUE (message_id)
)

    """
    )
    op.drop_constraint("ck_email_delivery_status", "email_deliveries", type_="check")
    op.create_check_constraint(
        "ck_email_delivery_status",
        "email_deliveries",
        "status IN ('queued','running','sent','failed','cancelled','unknown','blocked')",
    )
    op.execute(
        """

        CREATE OR REPLACE FUNCTION a2_immutable_approval() RETURNS trigger LANGUAGE
plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Approval requests cannot be deleted' USING ERRCODE =
'23514';
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
                (OLD.status = 'APPROVED' AND NEW.status IN
('EXPIRED','REVOKED','CONSUMED'))
            ) THEN
                RAISE EXCEPTION 'Illegal A2 approval transition' USING ERRCODE = '23514';
            END IF;
            IF OLD.approved_at IS NOT NULL AND
ROW(NEW.approved_by_user_id,NEW.approved_at,
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
            IF NEW.status = 'CONSUMED' AND OLD.status <> 'CONSUMED' AND NOT EXISTS (
                SELECT 1 FROM email_send_attempts a
                JOIN approved_email_reservations r ON r.id = a.reservation_id
                WHERE r.approval_id = NEW.id AND a.result = 'STARTED'
                  AND a.payload_hash = NEW.payload_hash AND a.payload_version =
NEW.payload_version
            ) THEN
                RAISE EXCEPTION 'Durable dispatch evidence required' USING ERRCODE =
'23514';
            END IF;
            RETURN NEW;
        END $$;

    """
    )
    op.execute(
        """
CREATE FUNCTION approved_email_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Email reservation is immutable' USING ERRCODE = '23514';
END $$;
CREATE TRIGGER approved_reservation_immutable BEFORE UPDATE OR DELETE ON
approved_email_reservations FOR EACH ROW EXECUTE FUNCTION approved_email_immutable();
    """
    )


def downgrade():
    op.execute(
        """
DO $$ BEGIN IF EXISTS (SELECT 1 FROM approved_email_reservations) OR EXISTS (SELECT 1 FROM
bulk_approval_proofs) THEN RAISE EXCEPTION 'Approval execution history exists; restore a
backup instead of destructive downgrade'; END IF; END $$
    """
    )
    op.execute(
        """

        CREATE OR REPLACE FUNCTION a2_immutable_approval() RETURNS trigger LANGUAGE
plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Approval requests cannot be deleted' USING ERRCODE =
'23514';
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
            IF OLD.approved_at IS NOT NULL AND
ROW(NEW.approved_by_user_id,NEW.approved_at,
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

    """
    )
    op.execute("DROP FUNCTION approved_email_immutable() CASCADE")
    op.drop_constraint("ck_email_delivery_status", "email_deliveries", type_="check")
    op.create_check_constraint(
        "ck_email_delivery_status",
        "email_deliveries",
        "status IN ('queued','running','sent','failed','cancelled')",
    )
    op.drop_table("email_send_attempts")
    op.drop_table("approved_email_reservations")
    op.drop_table("approved_email_batches")
    op.drop_table("bulk_approval_proofs")
