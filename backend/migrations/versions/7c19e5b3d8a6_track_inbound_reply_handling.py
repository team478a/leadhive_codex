"""track inbound reply handling"""

import sqlalchemy as sa
from alembic import op

revision = "7c19e5b3d8a6"
down_revision = "5a8e4d1c7f2b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inbound_emails", sa.Column("handled_by_user_id", sa.Uuid(), nullable=True))
    op.add_column("inbound_emails", sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_inbound_emails_handled_by_user_id",
        "inbound_emails",
        "users",
        ["handled_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_inbound_emails_handled_by_user_id", "inbound_emails", ["handled_by_user_id"]
    )
    op.create_index("ix_inbound_emails_handled_at", "inbound_emails", ["handled_at"])


def downgrade():
    op.drop_index("ix_inbound_emails_handled_at", table_name="inbound_emails")
    op.drop_index("ix_inbound_emails_handled_by_user_id", table_name="inbound_emails")
    op.drop_constraint("fk_inbound_emails_handled_by_user_id", "inbound_emails", type_="foreignkey")
    op.drop_column("inbound_emails", "handled_at")
    op.drop_column("inbound_emails", "handled_by_user_id")
