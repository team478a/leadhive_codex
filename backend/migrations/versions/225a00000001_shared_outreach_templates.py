"""Add organization-wide outreach templates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "225a00000001"
down_revision = "224a00000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outreach_templates",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
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
    op.create_foreign_key(
        "fk_outreach_templates_organization_id_organizations",
        "outreach_templates",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_outreach_templates_organization_id",
        "outreach_templates",
        ["organization_id"],
    )
    op.create_check_constraint(
        "ck_outreach_template_scope",
        "outreach_templates",
        "scope IN ('project', 'organization')",
    )
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
