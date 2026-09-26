"""add form intelligence phase 1"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2f6c8a9b1d4e"
down_revision = "f4c9d42b786e"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', "
        "'form_delivery', 'form_intelligence')",
    )
    op.create_table(
        "form_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("form_url", sa.Text(), nullable=False),
        sa.Column("form_index", sa.Integer(), nullable=False),
        sa.Column("form_status", sa.String(length=30), nullable=False),
        sa.Column("sales_contact_status", sa.String(length=20), nullable=False),
        sa.Column("captcha_type", sa.String(length=30), nullable=False),
        sa.Column("confirmation_page", sa.Boolean(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("form_found", sa.Boolean(), nullable=False),
        sa.Column("page_kind", sa.String(length=50), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=30), nullable=False),
        sa.Column("analysis_provider", sa.String(length=50), nullable=False),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("analysis_duration_ms >= 0", name="ck_form_profile_duration"),
        sa.CheckConstraint("form_index >= 0", name="ck_form_profile_form_index"),
        sa.CheckConstraint(
            "form_status IN ('UNANALYZED', 'READY', 'REVIEW_REQUIRED', 'BLOCKED', "
            "'STALE', 'ERROR')",
            name="ck_form_profile_status",
        ),
        sa.CheckConstraint(
            "sales_contact_status IN ('ALLOWED', 'PROHIBITED', 'UNCERTAIN')",
            name="ck_form_profile_sales_contact_status",
        ),
        sa.CheckConstraint(
            "captcha_type IN ('CAPTCHA_NONE', 'CAPTCHA_RECAPTCHA', 'CAPTCHA_HCAPTCHA', "
            "'CAPTCHA_TURNSTILE', 'CAPTCHA_OTHER')",
            name="ck_form_profile_captcha_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "form_url", "form_index", name="uq_form_profile_company_url_index"
        ),
    )
    op.create_index("ix_form_profiles_company_id", "form_profiles", ["company_id"])
    op.create_index("ix_form_profiles_form_status", "form_profiles", ["form_status"])
    op.create_index("ix_form_profiles_sales_contact_status", "form_profiles", ["sales_contact_status"])
    op.create_index("ix_form_profiles_is_primary", "form_profiles", ["is_primary"])
    op.create_index("ix_form_profiles_last_analyzed_at", "form_profiles", ["last_analyzed_at"])

    op.create_table(
        "form_profile_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("form_profile_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("selector", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("field_type", sa.String(length=50), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("mapped_key", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("decision_source", sa.String(length=20), nullable=False),
        sa.Column("recommended_value", sa.String(length=500), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("placeholder", sa.String(length=500), nullable=False),
        sa.Column("aria_label", sa.String(length=500), nullable=False),
        sa.Column("surrounding_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("position >= 0", name="ck_form_profile_field_position"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_form_profile_field_confidence"
        ),
        sa.CheckConstraint(
            "decision_source IN ('DOM', 'RULE', 'JEV', 'OPENAI', 'MANUAL')",
            name="ck_form_profile_field_decision_source",
        ),
        sa.ForeignKeyConstraint(["form_profile_id"], ["form_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_profile_id", "position", name="uq_form_profile_field_position"),
    )
    op.create_index("ix_form_profile_fields_form_profile_id", "form_profile_fields", ["form_profile_id"])
    op.create_index("ix_form_profile_fields_mapped_key", "form_profile_fields", ["mapped_key"])

    op.create_table(
        "form_analysis_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("form_profile_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_form_analysis_log_duration"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_form_analysis_log_confidence",
        ),
        sa.CheckConstraint(
            "event_type IN ('analysis_started', 'contact_page_found', 'form_found', "
            "'field_detected', 'field_mapped', 'ai_decision_requested', "
            "'ai_decision_completed', 'captcha_detected', 'sales_prohibition_detected', "
            "'analysis_completed', 'analysis_failed', 'manual_corrected')",
            name="ck_form_analysis_log_event_type",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["form_profile_id"], ["form_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_form_analysis_logs_company_id", "form_analysis_logs", ["company_id"])
    op.create_index("ix_form_analysis_logs_form_profile_id", "form_analysis_logs", ["form_profile_id"])
    op.create_index("ix_form_analysis_logs_actor_user_id", "form_analysis_logs", ["actor_user_id"])
    op.create_index("ix_form_analysis_logs_event_type", "form_analysis_logs", ["event_type"])


def downgrade():
    op.drop_index("ix_form_analysis_logs_event_type", table_name="form_analysis_logs")
    op.drop_index("ix_form_analysis_logs_actor_user_id", table_name="form_analysis_logs")
    op.drop_index("ix_form_analysis_logs_form_profile_id", table_name="form_analysis_logs")
    op.drop_index("ix_form_analysis_logs_company_id", table_name="form_analysis_logs")
    op.drop_table("form_analysis_logs")
    op.drop_index("ix_form_profile_fields_mapped_key", table_name="form_profile_fields")
    op.drop_index("ix_form_profile_fields_form_profile_id", table_name="form_profile_fields")
    op.drop_table("form_profile_fields")
    op.drop_index("ix_form_profiles_last_analyzed_at", table_name="form_profiles")
    op.drop_index("ix_form_profiles_is_primary", table_name="form_profiles")
    op.drop_index("ix_form_profiles_sales_contact_status", table_name="form_profiles")
    op.drop_index("ix_form_profiles_form_status", table_name="form_profiles")
    op.drop_index("ix_form_profiles_company_id", table_name="form_profiles")
    op.drop_table("form_profiles")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery')",
    )
