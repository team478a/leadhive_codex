import sqlalchemy as sa
from alembic import op

revision = "214a6f3c9b20"
down_revision = "b4f0a7c1e2d9"
branch_labels = None
depends_on = None


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _replace_source_constraint(expression):
    constraints = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("companies")
    }
    if "ck_company_source" in constraints:
        op.drop_constraint("ck_company_source", "companies", type_="check")
    op.create_check_constraint("ck_company_source", "companies", expression)


def upgrade():
    columns = _columns("companies")
    if "corporate_number" not in columns:
        op.add_column(
            "companies",
            sa.Column("corporate_number", sa.String(length=20), server_default="", nullable=False),
        )
    if "form_first_contact_url" not in columns:
        op.add_column(
            "companies",
            sa.Column("form_first_contact_url", sa.Text(), server_default="", nullable=False),
        )
    _replace_source_constraint(
        "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv', 'form_first')"
    )


def downgrade():
    op.execute("UPDATE companies SET source = 'serper' WHERE source = 'form_first'")
    _replace_source_constraint("source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv')")
    columns = _columns("companies")
    if "form_first_contact_url" in columns:
        op.drop_column("companies", "form_first_contact_url")
    if "corporate_number" in columns:
        op.drop_column("companies", "corporate_number")
