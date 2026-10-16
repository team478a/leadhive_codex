import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d27e6fb3a1c4"
down_revision = "3a8b2c1d4e5f"
branch_labels = None
depends_on = None


def _check_constraints() -> list[dict]:
    return sa.inspect(op.get_bind()).get_check_constraints("operation_jobs")


def upgrade():
    existing_constraint = next(
        (item for item in _check_constraints() if item["name"] == "ck_operation_job_type"), None
    )
    if existing_constraint is not None:
        op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_approval_batch', 'form_dm_readiness')",
    )

    inspector = sa.inspect(op.get_bind())
    if "form_dm_readiness_results" not in inspector.get_table_names():
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

    existing_indexes = {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes("form_dm_readiness_results")
    }
    indexes = (
        ("ix_form_dm_readiness_job_reason", ["job_id", "primary_reason"]),
        ("ix_form_dm_readiness_review_queue", ["job_id", "review_queue_eligible", "company_id"]),
        ("ix_form_dm_readiness_job_company", ["job_id", "company_id"]),
    )
    for name, columns in indexes:
        if name not in existing_indexes:
            op.create_index(name, "form_dm_readiness_results", columns)


def downgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_approval_batch')",
    )
