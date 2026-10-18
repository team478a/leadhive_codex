"""Allow isolated synthetic browser form analysis operations."""

from typing import Sequence, Union

from alembic import op

revision: str = "e2a6c1b8d904"
down_revision: Union[str, None] = "d3f8a1b6c907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "'collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', 'form_intelligence', "
    "'prepare_outreach', 'cf7_observation', 'extract_articles', 'form_dm_readiness', "
    "'form_approval_batch', 'bulk_template_drafts'"
)


def upgrade() -> None:
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        f"operation_type IN ({OLD_TYPES}, 'browser_form_analysis')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type", "operation_jobs", f"operation_type IN ({OLD_TYPES})"
    )
