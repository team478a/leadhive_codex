import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ff61aab29a10"
down_revision = ("ff51ac0e6437", "1bf54b61cc07")
branch_labels = None
depends_on = None


OLD_TYPES = (
    "'collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', 'form_intelligence', "
    "'prepare_outreach', 'cf7_observation'"
)
NEW_TYPES = OLD_TYPES + ", 'extract_articles'"


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type", "operation_jobs", f"operation_type IN ({NEW_TYPES})"
    )
    op.create_table(
        "collection_article_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operation_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("operation_jobs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "discovery_hit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_discovery_hits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("article_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("body_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("page_kind", sa.String(30), nullable=False, server_default=""),
        sa.Column("pattern", sa.String(30), nullable=False, server_default=""),
        sa.Column("extractor_version", sa.String(30), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("linked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name_only_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('FETCHED','ROBOTS_DISALLOWED','FETCH_FAILED','NOT_HTML','TOO_LARGE',"
            "'NOT_LIST','UNSUPPORTED','EXTRACTED')",
            name="ck_article_extraction_status",
        ),
        sa.UniqueConstraint(
            "project_id",
            "discovery_hit_id",
            "extractor_version",
            name="uq_article_extraction_hit_version",
        ),
    )
    op.create_index(
        "ix_collection_article_extractions_project_id",
        "collection_article_extractions",
        ["project_id"],
    )
    op.create_index(
        "ix_collection_article_extractions_operation_job_id",
        "collection_article_extractions",
        ["operation_job_id"],
    )
    op.create_index(
        "ix_collection_article_extractions_discovery_hit_id",
        "collection_article_extractions",
        ["discovery_hit_id"],
    )
    op.create_table(
        "collection_extracted_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "extraction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_article_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False),
        sa.Column("link_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("link_kind", sa.String(30), nullable=False, server_default=""),
        sa.Column("website_candidate", sa.Text(), nullable=False, server_default=""),
        sa.Column("pattern", sa.String(30), nullable=False, server_default=""),
        sa.Column("locator", sa.String(500), nullable=False, server_default=""),
        sa.Column("context", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("disposition", sa.String(30), nullable=False, server_default="NOT_INGESTED"),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "collection_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_jobs.id", ondelete="SET NULL"),
        ),
        sa.CheckConstraint(
            "status IN ('LINKED','NAME_ONLY','REJECTED')", name="ck_extracted_entry_status"
        ),
        sa.CheckConstraint(
            "disposition IN ('NOT_INGESTED','SAVED','DUPLICATE','SUPPRESSED',"
            "'AGGREGATOR_EXCLUDED','NON_COMPANY_SOURCE','INGESTION_CONFLICT')",
            name="ck_extracted_entry_disposition",
        ),
        sa.UniqueConstraint("extraction_id", "entry_order", name="uq_extracted_entry_order"),
    )
    for col in ("extraction_id", "company_id", "collection_job_id"):
        op.create_index(
            f"ix_collection_extracted_entries_{col}", "collection_extracted_entries", [col]
        )


def downgrade():
    op.drop_table("collection_extracted_entries")
    op.drop_table("collection_article_extractions")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type", "operation_jobs", f"operation_type IN ({OLD_TYPES})"
    )
