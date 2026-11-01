"""Add organization-wide outreach templates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "225a00000001"
down_revision = "224a00000001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("outreach_templates")}
    if "organization_id" not in columns:
        op.add_column(
            "outreach_templates",
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "scope" not in columns:
        op.add_column(
            "outreach_templates",
            sa.Column("scope", sa.String(length=20), server_default="project", nullable=False),
        )
    op.execute(
        "UPDATE outreach_templates AS template "
        "SET organization_id = project.organization_id "
        "FROM projects AS project WHERE project.id = template.project_id"
    )
    op.alter_column("outreach_templates", "organization_id", nullable=False)
    op.alter_column("outreach_templates", "project_id", nullable=True)
    foreign_keys = {key["name"] for key in inspector.get_foreign_keys("outreach_templates")}
    if "fk_outreach_templates_organization_id_organizations" not in foreign_keys:
        op.create_foreign_key(
            "fk_outreach_templates_organization_id_organizations",
            "outreach_templates",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )
    indexes = {index["name"] for index in inspector.get_indexes("outreach_templates")}
    if "ix_outreach_templates_organization_id" not in indexes:
        op.create_index(
            "ix_outreach_templates_organization_id",
            "outreach_templates",
            ["organization_id"],
        )
    checks = {check["name"] for check in inspector.get_check_constraints("outreach_templates")}
    if "ck_outreach_template_scope" not in checks:
        op.create_check_constraint(
            "ck_outreach_template_scope",
            "outreach_templates",
            "scope IN ('project', 'organization')",
        )
    if "ck_outreach_template_scope_owner" not in checks:
        op.create_check_constraint(
            "ck_outreach_template_scope_owner",
            "outreach_templates",
            "(scope = 'project' AND project_id IS NOT NULL) OR "
            "(scope = 'organization' AND project_id IS NULL)",
        )


def downgrade():
    op.execute("DELETE FROM outreach_templates WHERE scope = 'organization'")
    op.drop_constraint("ck_outreach_template_scope_owner", "outreach_templates", type_="check")
    op.drop_constraint("ck_outreach_template_scope", "outreach_templates", type_="check")
    op.drop_index("ix_outreach_templates_organization_id", table_name="outreach_templates")
    op.drop_constraint(
        "fk_outreach_templates_organization_id_organizations",
        "outreach_templates",
        type_="foreignkey",
    )
    op.alter_column("outreach_templates", "project_id", nullable=False)
    op.drop_column("outreach_templates", "scope")
    op.drop_column("outreach_templates", "organization_id")
