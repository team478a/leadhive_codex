"""P2 controlled CF7 evidence; no execution authority."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0152bc1f7548"
down_revision = "ff51ac0e6437"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cf7_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("form_profile_id", sa.Uuid(), sa.ForeignKey("form_profiles.id"), nullable=False),
        sa.Column("source_kind", sa.String(30), nullable=False),
        sa.Column("observer_version", sa.String(30), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_snapshot", JSONB(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("source_kind='CONTROLLED_FIXTURE'", name="ck_cf7_observation_source"),
        sa.CheckConstraint(
            "expires_at > observed_at AND expires_at <= observed_at + interval '24 hours'",
            name="ck_cf7_observation_expiry",
        ),
    )
    for name in ("project_id", "company_id", "form_profile_id"):
        op.create_index("ix_cf7_observations_" + name, "cf7_observations", [name])
    op.execute("""CREATE FUNCTION cf7_observation_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      RAISE EXCEPTION 'CF7 evidence is append only' USING ERRCODE='23514';
    END $$;
    CREATE TRIGGER cf7_observation_append_only BEFORE UPDATE OR DELETE OR TRUNCATE
      ON cf7_observations FOR EACH STATEMENT EXECUTE FUNCTION cf7_observation_immutable();
    CREATE FUNCTION cf7_observation_binding() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM companies c JOIN form_profiles f ON f.company_id=c.id
        WHERE c.id=NEW.company_id AND c.project_id=NEW.project_id AND f.id=NEW.form_profile_id)
      THEN RAISE EXCEPTION 'CF7 evidence ownership mismatch' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER cf7_observation_binding_guard BEFORE INSERT ON cf7_observations
      FOR EACH ROW EXECUTE FUNCTION cf7_observation_binding();""")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM cf7_observations) THEN
        RAISE EXCEPTION 'CF7 evidence exists; downgrade forbidden' USING ERRCODE='23514';
      END IF;
    END $$;
    DROP FUNCTION cf7_observation_immutable() CASCADE;
    DROP FUNCTION cf7_observation_binding() CASCADE;
    """)
    op.drop_table("cf7_observations")
