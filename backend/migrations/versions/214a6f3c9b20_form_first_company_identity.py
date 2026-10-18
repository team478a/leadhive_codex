import sqlalchemy as sa
from alembic import op

revision = "214a6f3c9b20"
down_revision = "b4f0a7c1e2d9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column("corporate_number", sa.String(length=20), server_default="", nullable=False),
    )
    op.add_column(
        "companies",
        sa.Column("form_first_contact_url", sa.Text(), server_default="", nullable=False),
    )
    op.drop_constraint("ck_company_source", "companies", type_="check")
    op.create_check_constraint(
        "ck_company_source",
        "companies",
        "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv', 'form_first')",
    )


def downgrade():
    op.execute("UPDATE companies SET source = 'serper' WHERE source = 'form_first'")
    op.drop_constraint("ck_company_source", "companies", type_="check")
    op.create_check_constraint(
        "ck_company_source",
        "companies",
        "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv')",
    )
    op.drop_column("companies", "form_first_contact_url")
    op.drop_column("companies", "corporate_number")
