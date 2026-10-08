"""link notifications to inbound replies"""

import sqlalchemy as sa
from alembic import op

revision = "5a8e4d1c7f2b"
down_revision = "0b36d7e29a5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("inbound_email_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_inbound_email_id",
        "notifications",
        "inbound_emails",
        ["inbound_email_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_notifications_inbound_email_id", "notifications", ["inbound_email_id"])


def downgrade():
    op.drop_index("ix_notifications_inbound_email_id", table_name="notifications")
    op.drop_constraint("fk_notifications_inbound_email_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "inbound_email_id")
