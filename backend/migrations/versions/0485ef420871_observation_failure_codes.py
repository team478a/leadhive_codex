"""Extend closed diagnostic reasons without changing historical ledger records."""

from alembic import op

revision = "0485ef420871"
down_revision = "0374de319760"
branch_labels = None
depends_on = None

OLD = (
    "'QUEUED','CLAIMED','CANCELLED','EVIDENCE_SAVED','CLAIM_REJECTED',"
    "'OBSERVATION_FAILED','BINDING_CHANGED','LEASE_CHANGED','WORKER_LOST',"
    "'PERMISSION_CHANGED','SOURCE_CHANGED','LAB_DISABLED'"
)
NEW = (
    OLD + ",'RUNNER_STOPPED','OBSERVATION_TIMEOUT','OBSERVATION_DNS_FAILED',"
    "'OBSERVATION_UNSAFE_DNS','OBSERVATION_TLS_FAILED','OBSERVATION_NETWORK_FAILED',"
    "'OBSERVATION_HTTP_REJECTED','OBSERVATION_RESPONSE_INVALID','OBSERVATION_ROBOTS_DENIED',"
    "'OBSERVATION_ROBOTS_INVALID','OBSERVATION_PARSE_FAILED','OBSERVATION_CONTRACT_INVALID',"
    "'OBSERVATION_STORAGE_FAILED'"
)


def upgrade():
    op.drop_constraint("ck_observation_job_reason", "form_observation_job_events", type_="check")
    op.create_check_constraint(
        "ck_observation_job_reason", "form_observation_job_events", "reason_code IN (" + NEW + ")"
    )


def downgrade():
    # Append-only history must never be rewritten just to permit downgrade.
    op.execute(
        """DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM form_observation_job_events WHERE reason_code NOT IN ("""
        + OLD
        + """))
    THEN RAISE EXCEPTION 'New diagnostic history prevents downgrade' USING ERRCODE='23514';
    END IF; END $$;"""
    )
    op.drop_constraint("ck_observation_job_reason", "form_observation_job_events", type_="check")
    op.create_check_constraint(
        "ck_observation_job_reason", "form_observation_job_events", "reason_code IN (" + OLD + ")"
    )
