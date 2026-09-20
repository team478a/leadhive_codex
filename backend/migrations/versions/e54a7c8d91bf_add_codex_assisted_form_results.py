"""add Codex-assisted form delivery results"""

import sqlalchemy as sa
from alembic import op

revision = "e54a7c8d91bf"
down_revision = "d83e6f149ab2"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_form_delivery_status", "form_deliveries", type_="check")
    op.add_column(
        "form_deliveries",
        sa.Column("delivery_method", sa.String(length=30), server_default="direct", nullable=False),
    )
    op.add_column(
        "form_deliveries",
        sa.Column("result_note", sa.String(length=500), server_default="", nullable=False),
    )
    op.alter_column("form_deliveries", "delivery_method", server_default=None)
    op.alter_column("form_deliveries", "result_note", server_default=None)
    op.create_check_constraint(
        "ck_form_delivery_status",
        "form_deliveries",
        "status IN ('pending', 'submitted', 'failed')",
    )
    op.create_check_constraint(
        "ck_form_delivery_method",
        "form_deliveries",
        "delivery_method IN ('direct', 'codex_assisted')",
    )
    op.create_index("ix_form_deliveries_delivery_method", "form_deliveries", ["delivery_method"])


def downgrade():
    op.drop_index("ix_form_deliveries_delivery_method", table_name="form_deliveries")
    op.drop_constraint("ck_form_delivery_method", "form_deliveries", type_="check")
    op.drop_constraint("ck_form_delivery_status", "form_deliveries", type_="check")
    op.execute("DELETE FROM form_deliveries WHERE status = 'pending'")
    op.create_check_constraint(
        "ck_form_delivery_status", "form_deliveries", "status IN ('submitted', 'failed')"
    )
    op.drop_column("form_deliveries", "result_note")
    op.drop_column("form_deliveries", "delivery_method")
