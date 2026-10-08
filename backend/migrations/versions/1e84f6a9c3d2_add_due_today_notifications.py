"""add due today notifications"""

from alembic import op

revision = "1e84f6a9c3d2"
down_revision = "7c19e5b3d8a6"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "notification_type IN "
        "('followup_overdue', 'operation_failed', 'email_delivery_failed', "
        "'inbound_reply_received', 'followup_due_today')",
    )


def downgrade():
    op.execute("DELETE FROM notifications WHERE notification_type = 'followup_due_today'")
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "notification_type IN "
        "('followup_overdue', 'operation_failed', 'email_delivery_failed', "
        "'inbound_reply_received')",
    )
