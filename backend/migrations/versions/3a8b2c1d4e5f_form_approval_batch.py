from alembic import op

revision = "3a8b2c1d4e5f"
down_revision = "1a8d65c3f02b"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness', 'form_approval_batch')",
    )


def downgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness')",
    )
