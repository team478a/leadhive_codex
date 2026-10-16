import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "1a8d65c3f02b"
down_revision = "ff61aab29a10"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness')",
    )
    op.create_table(
        "form_dm_readiness_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_reason", sa.String(length=40), nullable=False),
        sa.Column("secondary_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_queue_eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "classified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["operation_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["form_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "company_id", name="uq_form_dm_readiness_job_company"),
    )
    op.create_index(
        "ix_form_dm_readiness_job_reason",
        "form_dm_readiness_results",
        ["job_id", "primary_reason"],
    )
    op.create_index(
        "ix_form_dm_readiness_review_queue",
        "form_dm_readiness_results",
        ["job_id", "review_queue_eligible", "company_id"],
    )
    op.create_index(
        "ix_form_dm_readiness_job_company",
        "form_dm_readiness_results",
        ["job_id", "company_id"],
    )


def downgrade():
    op.drop_index("ix_form_dm_readiness_job_company", table_name="form_dm_readiness_results")
    op.drop_index("ix_form_dm_readiness_review_queue", table_name="form_dm_readiness_results")
    op.drop_index("ix_form_dm_readiness_job_reason", table_name="form_dm_readiness_results")
    op.drop_table("form_dm_readiness_results")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles')",
    )
