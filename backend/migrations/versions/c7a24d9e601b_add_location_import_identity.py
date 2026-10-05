"""Support location imports without conflating shared sites with company identity."""

import sqlalchemy as sa
from alembic import op

revision = "c7a24d9e601b"
down_revision = "a2f0c6d8e913"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column("record_type", sa.String(20), nullable=False, server_default="company"),
    )
    op.add_column(
        "companies", sa.Column("location_key", sa.String(64), nullable=False, server_default="")
    )
    op.add_column(
        "companies", sa.Column("reference_url", sa.Text(), nullable=False, server_default="")
    )
    op.create_check_constraint(
        "ck_company_record_type", "companies", "record_type IN ('company', 'location')"
    )
    op.create_check_constraint(
        "ck_company_location_key",
        "companies",
        "record_type <> 'location' OR length(location_key) = 64",
    )
    for field in ("domain", "website"):
        op.drop_constraint(f"uq_company_project_{field}", "companies", type_="unique")
        op.create_index(
            f"uq_company_project_{field}",
            "companies",
            ["project_id", "domain" if field == "domain" else "website_url"],
            unique=True,
            postgresql_where=sa.text("record_type = 'company'"),
        )
    op.drop_index("uq_company_project_name_address", table_name="companies")
    op.create_index(
        "uq_company_project_name_address",
        "companies",
        ["project_id", "company_name", "address"],
        unique=True,
        postgresql_where=sa.text("address <> '' AND record_type = 'company'"),
    )
    op.create_index(
        "uq_company_project_location",
        "companies",
        ["project_id", "location_key"],
        unique=True,
        postgresql_where=sa.text("record_type = 'location'"),
    )


def downgrade():
    # Old versions cannot represent distinct locations sharing one domain. Never discard them.
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM companies WHERE record_type = 'location'")
    ):
        raise RuntimeError(
            "Location records exist; keep this migration or explicitly migrate data first."
        )
    op.drop_index("uq_company_project_location", table_name="companies")
    op.drop_index("uq_company_project_name_address", table_name="companies")
    op.create_index(
        "uq_company_project_name_address",
        "companies",
        ["project_id", "company_name", "address"],
        unique=True,
        postgresql_where=sa.text("address <> ''"),
    )
    for field in ("domain", "website"):
        op.drop_index(f"uq_company_project_{field}", table_name="companies")
        op.create_unique_constraint(
            f"uq_company_project_{field}",
            "companies",
            ["project_id", "domain" if field == "domain" else "website_url"],
        )
    op.drop_constraint("ck_company_location_key", "companies", type_="check")
    op.drop_constraint("ck_company_record_type", "companies", type_="check")
    for field in ("reference_url", "location_key", "record_type"):
        op.drop_column("companies", field)
