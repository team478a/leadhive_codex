"""Persist stable recipient keys for cross-project cooldowns."""

import sqlalchemy as sa
from alembic import op

revision = "217a00000001"
down_revision = "216a00000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "approved_form_dispatches", sa.Column("recipient_key", sa.String(length=253), nullable=True)
    )
    op.add_column(
        "approved_form_dispatches",
        sa.Column("corporate_number", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "form_deliveries", sa.Column("recipient_key", sa.String(length=253), nullable=True)
    )
    op.add_column(
        "form_deliveries", sa.Column("corporate_number", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "form_dispatch_limits",
        sa.Column("recipient_cooldown_days", sa.Integer(), server_default="30", nullable=False),
    )
    op.add_column(
        "form_dispatch_limits",
        sa.Column("recipient_cooldown_limit", sa.Integer(), server_default="2", nullable=False),
    )
    op.create_check_constraint(
        "ck_form_recipient_cooldown_days",
        "form_dispatch_limits",
        "recipient_cooldown_days BETWEEN 1 AND 365",
    )
    op.create_check_constraint(
        "ck_form_recipient_cooldown_limit",
        "form_dispatch_limits",
        "recipient_cooldown_limit BETWEEN 1 AND 100",
    )
    op.create_index("ix_form_deliveries_recipient_key", "form_deliveries", ["recipient_key"])
    op.create_index("ix_form_deliveries_corporate_number", "form_deliveries", ["corporate_number"])
    op.create_index(
        "ix_approved_form_dispatches_recipient_key",
        "approved_form_dispatches",
        ["recipient_key"],
    )
    op.create_index(
        "ix_approved_form_dispatches_corporate_number",
        "approved_form_dispatches",
        ["corporate_number"],
    )


def downgrade():
    op.drop_constraint("ck_form_recipient_cooldown_limit", "form_dispatch_limits", type_="check")
    op.drop_constraint("ck_form_recipient_cooldown_days", "form_dispatch_limits", type_="check")
    op.drop_column("form_dispatch_limits", "recipient_cooldown_limit")
    op.drop_column("form_dispatch_limits", "recipient_cooldown_days")
    op.drop_index("ix_form_deliveries_corporate_number", table_name="form_deliveries")
    op.drop_index("ix_form_deliveries_recipient_key", table_name="form_deliveries")
    op.drop_column("form_deliveries", "corporate_number")
    op.drop_column("form_deliveries", "recipient_key")
    op.drop_index(
        "ix_approved_form_dispatches_corporate_number", table_name="approved_form_dispatches"
    )
    op.drop_index(
        "ix_approved_form_dispatches_recipient_key", table_name="approved_form_dispatches"
    )
    op.drop_column("approved_form_dispatches", "corporate_number")
    op.drop_column("approved_form_dispatches", "recipient_key")
