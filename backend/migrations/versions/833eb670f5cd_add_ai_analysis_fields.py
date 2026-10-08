"""add AI analysis fields."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "833eb670f5cd"
down_revision = "9acfc2e2665c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("companies", sa.Column("score", sa.Integer(), nullable=True))
    op.add_column("companies", sa.Column("rank", sa.String(length=20), nullable=True))
    op.add_column("companies", sa.Column("is_target", sa.Boolean(), nullable=True))
    text_default = sa.text("''")
    op.add_column(
        "companies",
        sa.Column(
            "business_type", sa.String(length=300), server_default=text_default, nullable=False
        ),
    )
    op.add_column(
        "companies", sa.Column("ai_summary", sa.Text(), server_default=text_default, nullable=False)
    )
    op.add_column(
        "companies", sa.Column("ai_reason", sa.Text(), server_default=text_default, nullable=False)
    )
    op.add_column(
        "companies",
        sa.Column(
            "ai_strengths",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "ai_concerns", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
    )
    op.add_column(
        "companies",
        sa.Column(
            "ai_recommended_approach", sa.Text(), server_default=text_default, nullable=False
        ),
    )
    op.add_column(
        "companies",
        sa.Column("ai_status", sa.String(length=30), server_default="pending", nullable=False),
    )
    op.add_column(
        "companies",
        sa.Column("ai_error", sa.String(length=500), server_default=text_default, nullable=False),
    )
    op.add_column(
        "companies",
        sa.Column("ai_provider", sa.String(length=50), server_default=text_default, nullable=False),
    )
    op.add_column(
        "companies",
        sa.Column("ai_model", sa.String(length=100), server_default=text_default, nullable=False),
    )
    op.add_column(
        "companies", sa.Column("ai_analyzed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_company_ai_status",
        "companies",
        "ai_status IN ('pending', 'running', 'completed', 'failed', 'skipped')",
    )
    op.create_check_constraint(
        "ck_company_score", "companies", "score IS NULL OR (score >= 0 AND score <= 100)"
    )
    op.create_check_constraint(
        "ck_company_rank", "companies", "rank IS NULL OR rank IN ('A', 'B', 'C', '対象外')"
    )
    op.create_index(op.f("ix_companies_ai_status"), "companies", ["ai_status"], unique=False)
    op.create_index(op.f("ix_companies_rank"), "companies", ["rank"], unique=False)
    op.create_index(op.f("ix_companies_score"), "companies", ["score"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_companies_score"), table_name="companies")
    op.drop_index(op.f("ix_companies_rank"), table_name="companies")
    op.drop_index(op.f("ix_companies_ai_status"), table_name="companies")
    op.drop_constraint("ck_company_rank", "companies", type_="check")
    op.drop_constraint("ck_company_score", "companies", type_="check")
    op.drop_constraint("ck_company_ai_status", "companies", type_="check")
    for column in (
        "ai_analyzed_at",
        "ai_model",
        "ai_provider",
        "ai_error",
        "ai_status",
        "ai_recommended_approach",
        "ai_concerns",
        "ai_strengths",
        "ai_reason",
        "ai_summary",
        "business_type",
        "is_target",
        "rank",
        "score",
    ):
        op.drop_column("companies", column)
