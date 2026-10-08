"""add company sales notes."""

import sqlalchemy as sa
from alembic import op

revision = "1129fe32eda3"
down_revision = "833eb670f5cd"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies", sa.Column("notes", sa.Text(), server_default=sa.text("''"), nullable=False)
    )
    op.create_check_constraint(
        "ck_company_sales_status",
        "companies",
        "status IN ('unreviewed', 'target', 'approached', 'replied', 'meeting', "
        "'won', 'lost', 'excluded')",
    )


def downgrade():
    op.drop_constraint("ck_company_sales_status", "companies", type_="check")
    op.drop_column("companies", "notes")
