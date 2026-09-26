"""add email delivery failure notifications"""

import sqlalchemy as sa
from alembic import op

revision = "9e5a8b40d12f"
down_revision = "5d81b9a27ce4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("email_delivery_id", sa.Uuid(), nullable=True))
    op.create_index("ix_notifications_email_delivery_id", "notifications", ["email_delivery_id"])
    op.create_foreign_key(
        "fk_notifications_email_delivery_id_email_deliveries",
        "notifications",
        "email_deliveries",
        ["email_delivery_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "notification_type IN ('followup_overdue', 'operation_failed', 'email_delivery_failed')",
    )


def downgrade():
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "notification_type IN ('followup_overdue', 'operation_failed')",
    )
    op.drop_constraint(
        "fk_notifications_email_delivery_id_email_deliveries",
        "notifications",
        type_="foreignkey",
    )
    op.drop_index("ix_notifications_email_delivery_id", table_name="notifications")
    op.drop_column("notifications", "email_delivery_id")
