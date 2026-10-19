"""Add site analysis jobs and the collection auto-analysis setting."""

import sqlalchemy as sa
from alembic import op

revision = "21501a000003"
down_revision = "21501a000002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "application_settings",
        sa.Column("auto_site_analysis", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness', 'form_approval_batch', 'bulk_template_drafts', "
        "'browser_form_analysis', 'site_analysis')",
    )


def downgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness', 'form_approval_batch', 'bulk_template_drafts', "
        "'browser_form_analysis')",
    )
    op.drop_column("application_settings", "auto_site_analysis")
