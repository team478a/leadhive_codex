"""Add source-attributed cross-project master data structures."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "216a00000001"
down_revision = "21501a000003"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _create_table_if_missing(name: str, *args, **kwargs) -> None:
    if not _table_exists(name):
        op.create_table(name, *args, **kwargs)


def _create_index_if_missing(name: str, table: str, columns, **kwargs) -> None:
    inspector = sa.inspect(op.get_bind())
    if not any(index["name"] == name for index in inspector.get_indexes(table)):
        op.create_index(name, table, columns, **kwargs)


def _create_foreign_key_if_missing(name: str, source_table: str, *args, **kwargs) -> None:
    inspector = sa.inspect(op.get_bind())
    if not any(item["name"] == name for item in inspector.get_foreign_keys(source_table)):
        op.create_foreign_key(name, source_table, *args, **kwargs)


def upgrade() -> None:
    checks = sa.inspect(op.get_bind()).get_check_constraints("operation_jobs")
    if any(item["name"] == "ck_operation_job_type" for item in checks):
        op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness', 'form_approval_batch', 'bulk_template_drafts', "
        "'browser_form_analysis', 'site_analysis', 'master_site_backfill')",
    )
    _create_table_if_missing(
        "master_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("corporate_number", sa.String(20)),
        sa.Column("name", sa.String(500), server_default="", nullable=False),
        sa.Column("prefecture", sa.String(20), server_default="", nullable=False),
        sa.Column("city", sa.String(200), server_default="", nullable=False),
        sa.Column("status", sa.String(20), server_default="unverified", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'closed', 'non_company', 'unverified')",
            name="ck_master_company_status",
        ),
    )
    _create_index_if_missing(
        "uq_master_company_corporate_number",
        "master_companies",
        ["corporate_number"],
        unique=True,
        postgresql_where=sa.text("corporate_number IS NOT NULL"),
    )
    _create_table_if_missing(
        "master_sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("host", sa.String(253), nullable=False, unique=True),
        sa.Column("registrable_domain", sa.String(253), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_site_name", sa.String(500), server_default="", nullable=False),
    )
    _create_index_if_missing(
        "ix_master_sites_registrable_domain", "master_sites", ["registrable_domain"]
    )
    _create_table_if_missing(
        "master_company_sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "master_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("master_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "master_site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("master_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "relation IN ('primary', 'brand', 'store', 'unknown')",
            name="ck_master_company_site_relation",
        ),
        sa.UniqueConstraint(
            "master_company_id",
            "master_site_id",
            "observed_at",
            name="uq_master_company_site_observed",
        ),
    )
    _create_index_if_missing(
        "ix_master_company_sites_master_company_id", "master_company_sites", ["master_company_id"]
    )
    _create_index_if_missing(
        "ix_master_company_sites_master_site_id", "master_company_sites", ["master_site_id"]
    )
    _create_index_if_missing(
        "ix_master_company_site_active", "master_company_sites", ["master_site_id", "valid_until"]
    )
    _create_table_if_missing(
        "master_contact_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "master_site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("master_sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.String(30), server_default="contact", nullable=False),
        sa.Column("sales_prohibited", sa.Boolean()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    )
    _create_index_if_missing(
        "ix_master_contact_pages_master_site_id", "master_contact_pages", ["master_site_id"]
    )
    _create_table_if_missing(
        "master_form_structures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "master_contact_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("master_contact_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("form_index", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("fields", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("captcha_type", sa.String(30), server_default="CAPTCHA_NONE", nullable=False),
        sa.Column("submission_kind", sa.String(50), server_default="", nullable=False),
        sa.Column("confirmation_page", sa.Boolean()),
        sa.Column("analysis_version", sa.String(30), nullable=False),
        sa.Column(
            "analyzed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("form_index >= 0", name="ck_master_form_structure_index"),
        sa.UniqueConstraint(
            "master_contact_page_id",
            "form_index",
            "fingerprint",
            name="uq_master_form_structure_fingerprint",
        ),
    )
    _create_index_if_missing(
        "ix_master_form_structures_master_contact_page_id",
        "master_form_structures",
        ["master_contact_page_id"],
    )
    _create_table_if_missing(
        "master_form_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("contact_page_url", sa.Text(), nullable=False),
        sa.Column("contact_page_hash", sa.String(64), nullable=False),
        sa.Column("form_index", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("fields_hash", sa.String(64), nullable=False),
        sa.Column("mapping_snapshot", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("confirmed_no_sales_prohibition", sa.Boolean(), nullable=False),
        sa.Column(
            "confirmed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("form_index >= 0", name="ck_master_form_review_form_index"),
        sa.UniqueConstraint(
            "organization_id",
            "contact_page_hash",
            "form_index",
            "fingerprint",
            name="uq_master_form_review_org_page_form",
        ),
    )
    _create_index_if_missing(
        "ix_master_form_reviews_organization_id", "master_form_reviews", ["organization_id"]
    )
    _create_index_if_missing(
        "ix_master_form_reviews_confirmed_by_user_id",
        "master_form_reviews",
        ["confirmed_by_user_id"],
    )
    _create_table_if_missing(
        "master_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "master_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("master_companies.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "master_site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("master_sites.id", ondelete="CASCADE"),
        ),
        sa.Column("field", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB()),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("source_url", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "observed_by_org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.CheckConstraint(
            "(master_company_id IS NOT NULL)::int + (master_site_id IS NOT NULL)::int = 1",
            name="ck_master_observation_subject",
        ),
        sa.CheckConstraint(
            "source IN ('site', 'nta', 'gbizinfo', 'form_first', 'google_places')",
            name="ck_master_observation_source",
        ),
        sa.CheckConstraint(
            "source <> 'google_places' OR field = 'place_id'",
            name="ck_master_observation_google_place_id_only",
        ),
    )
    _create_index_if_missing(
        "ix_master_observation_company_field_time",
        "master_observations",
        ["master_company_id", "field", "observed_at"],
    )
    _create_index_if_missing(
        "ix_master_observation_site_field_time",
        "master_observations",
        ["master_site_id", "field", "observed_at"],
    )
    _create_index_if_missing(
        "ix_master_observations_observed_by_org_id", "master_observations", ["observed_by_org_id"]
    )
    company_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("companies")}
    if "master_company_id" not in company_columns:
        op.add_column(
            "companies",
            sa.Column("master_company_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "master_site_id" not in company_columns:
        op.add_column(
            "companies",
            sa.Column("master_site_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    _create_foreign_key_if_missing(
        "fk_companies_master_company_id_master_companies",
        "companies",
        "master_companies",
        ["master_company_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _create_foreign_key_if_missing(
        "fk_companies_master_site_id_master_sites",
        "companies",
        "master_sites",
        ["master_site_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _create_index_if_missing("ix_companies_master_company_id", "companies", ["master_company_id"])
    _create_index_if_missing("ix_companies_master_site_id", "companies", ["master_site_id"])


def downgrade() -> None:
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint(
        "ck_operation_job_type",
        "operation_jobs",
        "operation_type IN ('collect_search', 'web_analysis', 'ai_analysis', 'form_delivery', "
        "'form_intelligence', 'prepare_outreach', 'cf7_observation', 'extract_articles', "
        "'form_dm_readiness', 'form_approval_batch', 'bulk_template_drafts', "
        "'browser_form_analysis', 'site_analysis')",
    )
    op.drop_index("ix_companies_master_site_id", table_name="companies")
    op.drop_index("ix_companies_master_company_id", table_name="companies")
    op.drop_constraint("fk_companies_master_site_id_master_sites", "companies", type_="foreignkey")
    op.drop_constraint(
        "fk_companies_master_company_id_master_companies", "companies", type_="foreignkey"
    )
    op.drop_column("companies", "master_site_id")
    op.drop_column("companies", "master_company_id")
    op.drop_index("ix_master_observations_observed_by_org_id", table_name="master_observations")
    op.drop_index("ix_master_observation_site_field_time", table_name="master_observations")
    op.drop_index("ix_master_observation_company_field_time", table_name="master_observations")
    op.drop_table("master_observations")
    op.drop_index("ix_master_form_reviews_confirmed_by_user_id", table_name="master_form_reviews")
    op.drop_index("ix_master_form_reviews_organization_id", table_name="master_form_reviews")
    op.drop_table("master_form_reviews")
    op.drop_index(
        "ix_master_form_structures_master_contact_page_id", table_name="master_form_structures"
    )
    op.drop_table("master_form_structures")
    op.drop_index("ix_master_contact_pages_master_site_id", table_name="master_contact_pages")
    op.drop_table("master_contact_pages")
    op.drop_index("ix_master_company_site_active", table_name="master_company_sites")
    op.drop_index("ix_master_company_sites_master_site_id", table_name="master_company_sites")
    op.drop_index("ix_master_company_sites_master_company_id", table_name="master_company_sites")
    op.drop_table("master_company_sites")
    op.drop_index("ix_master_sites_registrable_domain", table_name="master_sites")
    op.drop_table("master_sites")
    op.drop_index("uq_master_company_corporate_number", table_name="master_companies")
    op.drop_table("master_companies")
