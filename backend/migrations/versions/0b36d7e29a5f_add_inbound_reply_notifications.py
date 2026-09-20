"""add inbound reply notifications"""

from alembic import op

revision = "0b36d7e29a5f"
down_revision = "6d28a1ce4f7b"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "notification_type IN "
        "('followup_overdue', 'operation_failed', 'email_delivery_failed', "
        "'inbound_reply_received')",
    )


def downgrade():
    op.execute("DELETE FROM notifications WHERE notification_type = 'inbound_reply_received'")
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "notification_type IN ('followup_overdue', 'operation_failed', 'email_delivery_failed')",
    )
