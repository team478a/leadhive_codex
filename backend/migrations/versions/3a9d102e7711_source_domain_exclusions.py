"""Human-confirmed, project-local source exclusions."""

import sqlalchemy as sa
from alembic import op

revision = "3a9d102e7711"
down_revision = "2f178bf991d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_domain_exclusions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("evidence_url", sa.String(2048), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("history", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("project_id", "domain", name="uq_source_domain_project"),
    )
    op.create_index(
        "ix_source_domain_exclusions_project_id", "source_domain_exclusions", ["project_id"]
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS(SELECT 1 FROM source_domain_exclusions)"))
        .scalar()
    ):
        raise RuntimeError("Source exclusions exist; export and archive them before downgrade")
    op.drop_table("source_domain_exclusions")
