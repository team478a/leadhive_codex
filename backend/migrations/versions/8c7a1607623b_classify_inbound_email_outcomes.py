"""classify inbound email outcomes"""

import sqlalchemy as sa
from alembic import op

revision = "8c7a1607623b"
down_revision = "648941086ddb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "inbound_emails",
        sa.Column(
            "classification",
            sa.String(length=20),
            server_default=sa.text("'reply'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_inbound_email_classification",
        "inbound_emails",
        "classification IN ('reply', 'bounce', 'unsubscribe', 'other')",
    )
    op.alter_column("inbound_emails", "classification", server_default=None)


def downgrade():
    op.drop_constraint("ck_inbound_email_classification", "inbound_emails", type_="check")
    op.drop_column("inbound_emails", "classification")
