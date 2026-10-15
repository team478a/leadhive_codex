"""Normal Serper discovery observations before filtering."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "18dc401aa791"
down_revision = "07ab219ec430"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "collection_jobs",
        sa.Column("discovery_summary", postgresql.JSONB(), server_default="{}", nullable=False),
    )
    op.create_table(
        "collection_discovery_hits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "collection_job_id",
            sa.Uuid(),
            sa.ForeignKey("collection_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("classification_version", sa.String(20), nullable=False),
        sa.Column("classification_reason", sa.String(100), nullable=False),
        sa.Column("disposition", sa.String(30), nullable=False),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="SET NULL")),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_job_id", "position", name="uq_discovery_hit_position"),
        sa.CheckConstraint("position BETWEEN 1 AND 100", name="ck_discovery_hit_position"),
        sa.CheckConstraint(
            "disposition IN ('CAPTURED','SAVED','DUPLICATE','SUPPRESSED',"
            "'AGGREGATOR_EXCLUDED','TARGET_LIMIT','RESPONSE_LIMIT','INVALID_URL',"
            "'NON_COMPANY_SOURCE','INGESTION_CONFLICT')",
            name="ck_discovery_hit_disposition",
        ),
    )
    for column in ("collection_job_id", "company_id"):
        op.create_index(
            f"ix_collection_discovery_hits_{column}", "collection_discovery_hits", [column]
        )
    op.execute("""
    CREATE FUNCTION collection_discovery_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'UPDATE' AND
        ROW(NEW.id, NEW.collection_job_id, NEW.position, NEW.snapshot,
            NEW.raw_hash, NEW.observed_at, NEW.retain_until)
        IS DISTINCT FROM
        ROW(OLD.id, OLD.collection_job_id, OLD.position, OLD.snapshot,
            OLD.raw_hash, OLD.observed_at, OLD.retain_until)
      THEN
        RAISE EXCEPTION 'discovery snapshot is immutable' USING ERRCODE='23514';
      END IF;
      IF NEW.company_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM companies c JOIN collection_jobs j ON j.project_id=c.project_id
        WHERE c.id=NEW.company_id AND j.id=NEW.collection_job_id
      ) THEN
        RAISE EXCEPTION 'discovery company crosses project' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER collection_discovery_snapshot BEFORE INSERT OR UPDATE
      ON collection_discovery_hits
      FOR EACH ROW EXECUTE FUNCTION collection_discovery_guard();
    """)


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM collection_discovery_hits)"))
        .scalar()
    ):
        raise RuntimeError("Discovery observations exist; archive them before downgrade")
    op.drop_table("collection_discovery_hits")
    op.execute("DROP FUNCTION collection_discovery_guard()")
    op.drop_column("collection_jobs", "discovery_summary")
