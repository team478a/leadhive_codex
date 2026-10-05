"""Index recipient duplicate checks for large reservation lists."""

from alembic import op

revision = "f5d92b70e316"
down_revision = "f4c83a61d205"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX ix_email_destination_guard "
        "ON email_deliveries (lower(recipient_email), status)"
    )


def downgrade():
    op.drop_index("ix_email_destination_guard", table_name="email_deliveries")
