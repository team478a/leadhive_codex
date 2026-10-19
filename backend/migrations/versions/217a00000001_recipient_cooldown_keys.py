"""Persist stable recipient keys for cross-project cooldowns."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "217a00000001"
down_revision = "216a00000001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    columns = {
        "approved_form_dispatches": (
            sa.Column("recipient_key", sa.String(length=253), nullable=True),
            sa.Column("corporate_number", sa.String(length=20), nullable=True),
        ),
        "form_deliveries": (
            sa.Column("recipient_key", sa.String(length=253), nullable=True),
            sa.Column("corporate_number", sa.String(length=20), nullable=True),
        ),
        "form_dispatch_limits": (
            sa.Column("recipient_cooldown_days", sa.Integer(), server_default="30", nullable=False),
            sa.Column("recipient_cooldown_limit", sa.Integer(), server_default="2", nullable=False),
        ),
    }
    for table_name, table_columns in columns.items():
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table_columns:
            if column.name not in existing:
                op.add_column(table_name, column)

    checks = {
        "ck_form_recipient_cooldown_days": "recipient_cooldown_days BETWEEN 1 AND 365",
        "ck_form_recipient_cooldown_limit": "recipient_cooldown_limit BETWEEN 1 AND 100",
    }
    existing_checks = {
        constraint["name"]
        for constraint in inspect(bind).get_check_constraints("form_dispatch_limits")
    }
    for name, condition in checks.items():
        if name not in existing_checks:
            op.create_check_constraint(name, "form_dispatch_limits", condition)

    indexes = (
        ("ix_form_deliveries_recipient_key", "form_deliveries", ["recipient_key"]),
        ("ix_form_deliveries_corporate_number", "form_deliveries", ["corporate_number"]),
        (
            "ix_approved_form_dispatches_recipient_key",
            "approved_form_dispatches",
            ["recipient_key"],
        ),
        (
            "ix_approved_form_dispatches_corporate_number",
            "approved_form_dispatches",
            ["corporate_number"],
        ),
    )
    for name, table_name, column_names in indexes:
        existing_indexes = {index["name"] for index in inspect(bind).get_indexes(table_name)}
        if name not in existing_indexes:
            op.create_index(name, table_name, column_names)


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
