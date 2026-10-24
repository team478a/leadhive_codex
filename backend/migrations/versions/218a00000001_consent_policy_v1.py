"""Add project-scoped consent policy decisions."""

import sqlalchemy as sa
from alembic import op

revision = "218a00000001"
down_revision = "217a00000001"
branch_labels = None
depends_on = None

OLD_OPERATION_TYPES = (
    "'collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
    "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
    "'form_dm_readiness', 'form_approval_batch', 'bulk_template_drafts', "
    "'browser_form_analysis', 'site_analysis', 'master_site_backfill'"
)
OLD_DECISION_SOURCES = "'DOM', 'RULE', 'JEV', 'OPENAI', 'MANUAL'"
OLD_LOG_TYPES = (
    "'analysis_started', 'contact_page_found', 'form_found', 'field_detected', "
    "'field_mapped', 'ai_decision_requested', 'ai_decision_completed', "
    "'captcha_detected', 'sales_prohibition_detected', 'analysis_completed', "
    "'analysis_failed', 'manual_corrected'"
)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("projects")}
    columns = (
        sa.Column("consent_policy_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "consent_policy_version", sa.String(length=50), server_default="", nullable=False
        ),
        sa.Column("consent_policy_enabled_by_user_id", sa.UUID(), nullable=True),
        sa.Column("consent_policy_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        if column.name not in existing_columns:
            op.add_column("projects", column)

    foreign_key_name = "fk_projects_consent_policy_enabled_by_user_id_users"
    existing_foreign_keys = {
        foreign_key["name"] for foreign_key in sa.inspect(bind).get_foreign_keys("projects")
    }
    if foreign_key_name not in existing_foreign_keys:
        op.create_foreign_key(
            foreign_key_name,
            "projects",
            "users",
            ["consent_policy_enabled_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    index_name = "ix_projects_consent_policy_enabled_by_user_id"
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("projects")}
    if index_name not in existing_indexes:
        op.create_index(index_name, "projects", ["consent_policy_enabled_by_user_id"])

    _replace_check(
        "ck_form_profile_field_decision_source",
        "form_profile_fields",
        f"decision_source IN ({OLD_DECISION_SOURCES}, 'POLICY')",
    )
    _replace_check(
        "ck_form_analysis_log_event_type",
        "form_analysis_logs",
        f"event_type IN ({OLD_LOG_TYPES}, 'policy_applied')",
    )
    _replace_check(
        "ck_operation_job_type",
        "operation_jobs",
        f"operation_type IN ({OLD_OPERATION_TYPES}, 'consent_policy')",
    )


def _replace_check(name: str, table_name: str, condition: str) -> None:
    existing = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name)
    }
    if name in existing:
        op.drop_constraint(name, table_name, type_="check")
    op.create_check_constraint(name, table_name, condition)


def downgrade():
    op.execute(
        "UPDATE form_profile_fields SET decision_source='RULE', recommended_value='', "
        "confidence=0 WHERE decision_source='POLICY'"
    )
    op.execute("DELETE FROM form_analysis_logs WHERE event_type='policy_applied'")
    op.execute("DELETE FROM operation_jobs WHERE operation_type='consent_policy'")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type", "operation_jobs", f"operation_type IN ({OLD_OPERATION_TYPES})"
    )
    op.drop_constraint("ck_form_analysis_log_event_type", "form_analysis_logs", type_="check")
    op.create_check_constraint(
        "ck_form_analysis_log_event_type",
        "form_analysis_logs",
        f"event_type IN ({OLD_LOG_TYPES})",
    )
    op.drop_constraint(
        "ck_form_profile_field_decision_source", "form_profile_fields", type_="check"
    )
    op.create_check_constraint(
        "ck_form_profile_field_decision_source",
        "form_profile_fields",
        f"decision_source IN ({OLD_DECISION_SOURCES})",
    )
    op.drop_index("ix_projects_consent_policy_enabled_by_user_id", table_name="projects")
    op.drop_constraint(
        "fk_projects_consent_policy_enabled_by_user_id_users", "projects", type_="foreignkey"
    )
    op.drop_column("projects", "consent_policy_enabled_at")
    op.drop_column("projects", "consent_policy_enabled_by_user_id")
    op.drop_column("projects", "consent_policy_version")
    op.drop_column("projects", "consent_policy_enabled")
