"""Persist safe AI suggestions for project form label rules."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "223a00000001"
down_revision = "222a00000001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "form_label_ai_suggestions" not in inspector.get_table_names():
        op.create_table(
            "form_label_ai_suggestions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("project_id", sa.UUID(), nullable=False),
            sa.Column("normalized_label", sa.Text(), nullable=False),
            sa.Column("field_type", sa.String(length=50), nullable=False),
            sa.Column(
                "suggested_mapped_key",
                sa.String(length=50),
                server_default="unknown",
                nullable=False,
            ),
            sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=50), server_default="", nullable=False),
            sa.Column("model", sa.String(length=100), server_default="", nullable=False),
            sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
            sa.Column("reason", sa.String(length=500), server_default="", nullable=False),
            sa.Column(
                "usage",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("created_by_user_id", sa.UUID(), nullable=True),
            sa.Column("accepted_rule_id", sa.UUID(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('ACTIVE', 'ACCEPTED', 'DISMISSED', 'UNAVAILABLE')",
                name="ck_form_label_ai_suggestion_status",
            ),
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name="ck_form_label_ai_suggestion_confidence",
            ),
            sa.CheckConstraint(
                "sample_count >= 1",
                name="ck_form_label_ai_suggestion_sample_count",
            ),
            sa.ForeignKeyConstraint(
                ["accepted_rule_id"], ["form_label_rules.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("form_label_ai_suggestions")}
    if "ix_form_label_ai_suggestions_project_id" not in indexes:
        op.create_index(
            "ix_form_label_ai_suggestions_project_id",
            "form_label_ai_suggestions",
            ["project_id"],
        )
    if "ix_form_label_ai_suggestions_created_by_user_id" not in indexes:
        op.create_index(
            "ix_form_label_ai_suggestions_created_by_user_id",
            "form_label_ai_suggestions",
            ["created_by_user_id"],
        )
    if "ix_form_label_ai_suggestions_accepted_rule_id" not in indexes:
        op.create_index(
            "ix_form_label_ai_suggestions_accepted_rule_id",
            "form_label_ai_suggestions",
            ["accepted_rule_id"],
        )
    if "uq_form_label_ai_suggestions_open_project_label_type" not in indexes:
        op.create_index(
            "uq_form_label_ai_suggestions_open_project_label_type",
            "form_label_ai_suggestions",
            ["project_id", "normalized_label", "field_type"],
            unique=True,
            postgresql_where=sa.text("status IN ('ACTIVE', 'UNAVAILABLE')"),
        )


def downgrade():
    op.drop_index(
        "uq_form_label_ai_suggestions_open_project_label_type",
        table_name="form_label_ai_suggestions",
    )
    op.drop_index(
        "ix_form_label_ai_suggestions_accepted_rule_id",
        table_name="form_label_ai_suggestions",
    )
    op.drop_index(
        "ix_form_label_ai_suggestions_created_by_user_id",
        table_name="form_label_ai_suggestions",
    )
    op.drop_index(
        "ix_form_label_ai_suggestions_project_id",
        table_name="form_label_ai_suggestions",
    )
    op.drop_table("form_label_ai_suggestions")
