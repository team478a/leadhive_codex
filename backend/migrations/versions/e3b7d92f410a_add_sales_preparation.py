"""Add resumable preparation without connecting dispatch."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e3b7d92f410a"
down_revision = "c7a24d9e601b"
branch_labels = None
depends_on = None


def type_constraint(include_preparation):
    kinds = "'collect_search','web_analysis','ai_analysis','form_delivery','form_intelligence'"
    return (
        "operation_type IN (" + kinds + (",'prepare_outreach'" if include_preparation else "") + ")"
    )


def upgrade():
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint("ck_operation_job_type", "operation_jobs", type_constraint(True))
    op.create_table(
        "sales_preparation_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("operation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.UUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("draft_id", sa.UUID(), sa.ForeignKey("outreach_drafts.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("job_id", "company_id", name="uq_preparation_job_company"),
        sa.CheckConstraint(
            "status IN ('pending','running','ready','review','blocked','error')",
            name="ck_preparation_status",
        ),
    )
    for field in ("job_id", "company_id", "status"):
        op.create_index(f"ix_sales_preparation_items_{field}", "sales_preparation_items", [field])


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM operation_jobs WHERE operation_type='prepare_outreach'")
    ):
        raise RuntimeError("Preparation jobs exist; preserve preparation history before downgrade.")
    op.drop_table("sales_preparation_items")
    op.drop_constraint("ck_operation_job_type", "operation_jobs", type_="check")
    op.create_check_constraint("ck_operation_job_type", "operation_jobs", type_constraint(False))
