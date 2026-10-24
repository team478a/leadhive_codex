"""Add project-scoped form label mapping rules."""

import sqlalchemy as sa
from alembic import op

revision = "222a00000001"
down_revision = "218a00000001"
branch_labels = None
depends_on = None

OLD_OPERATION_TYPES = (
    "'collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
    "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
    "'form_dm_readiness', 'form_approval_batch', 'bulk_template_drafts', "
    "'browser_form_analysis', 'site_analysis', 'master_site_backfill', 'consent_policy'"
)


def _replace_operation_check(condition: str) -> None:
    existing = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("operation_jobs")
    }
    if "ck_operation_job_type" in existing:
        op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint("ck_operation_job_type", "operation_jobs", condition)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "form_label_rules" not in inspector.get_table_names():
        op.create_table(
            "form_label_rules",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("project_id", sa.UUID(), nullable=False),
            sa.Column("normalized_label", sa.Text(), nullable=False),
            sa.Column("field_type", sa.String(length=50), nullable=False),
            sa.Column("mapped_key", sa.String(length=50), nullable=False),
            sa.Column(
                "recommended_value", sa.String(length=500), server_default="", nullable=False
            ),
            sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
            sa.Column("created_by_user_id", sa.UUID(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('ACTIVE', 'RETIRED')", name="ck_form_label_rule_status"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("form_label_rules")}
    if "ix_form_label_rules_project_id" not in indexes:
        op.create_index("ix_form_label_rules_project_id", "form_label_rules", ["project_id"])
    if "ix_form_label_rules_created_by_user_id" not in indexes:
        op.create_index(
            "ix_form_label_rules_created_by_user_id", "form_label_rules", ["created_by_user_id"]
        )
    if "uq_form_label_rules_active_project_label_type" not in indexes:
        op.create_index(
            "uq_form_label_rules_active_project_label_type",
            "form_label_rules",
            ["project_id", "normalized_label", "field_type"],
            unique=True,
            postgresql_where=sa.text("status = 'ACTIVE'"),
        )

    field_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("form_profile_fields")
    }
    if "label_rule_id" not in field_columns:
        op.add_column("form_profile_fields", sa.Column("label_rule_id", sa.UUID(), nullable=True))
    field_fks = {
        foreign_key["name"]
        for foreign_key in sa.inspect(bind).get_foreign_keys("form_profile_fields")
    }
    if "fk_form_profile_fields_label_rule_id_form_label_rules" not in field_fks:
        op.create_foreign_key(
            "fk_form_profile_fields_label_rule_id_form_label_rules",
            "form_profile_fields",
            "form_label_rules",
            ["label_rule_id"],
            ["id"],
            ondelete="SET NULL",
        )
    field_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("form_profile_fields")}
    if "ix_form_profile_fields_label_rule_id" not in field_indexes:
        op.create_index(
            "ix_form_profile_fields_label_rule_id", "form_profile_fields", ["label_rule_id"]
        )

    _replace_operation_check(f"operation_type IN ({OLD_OPERATION_TYPES}, 'form_label_rule')")


def downgrade():
    op.execute("DELETE FROM operation_jobs WHERE operation_type='form_label_rule'")
    _replace_operation_check(f"operation_type IN ({OLD_OPERATION_TYPES})")
    op.drop_index("ix_form_profile_fields_label_rule_id", table_name="form_profile_fields")
    op.drop_constraint(
        "fk_form_profile_fields_label_rule_id_form_label_rules",
        "form_profile_fields",
        type_="foreignkey",
    )
    op.drop_column("form_profile_fields", "label_rule_id")
    op.drop_index("uq_form_label_rules_active_project_label_type", table_name="form_label_rules")
    op.drop_index("ix_form_label_rules_created_by_user_id", table_name="form_label_rules")
    op.drop_index("ix_form_label_rules_project_id", table_name="form_label_rules")
    op.drop_table("form_label_rules")
