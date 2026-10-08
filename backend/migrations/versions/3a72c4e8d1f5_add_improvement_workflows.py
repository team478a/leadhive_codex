"""add improvement workflows and gBizINFO source"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3a72c4e8d1f5"
down_revision = "1e84f6a9c3d2"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_company_source", "companies", type_="check")
    op.create_check_constraint(
        "ck_company_source",
        "companies",
        "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv')",
    )
    op.drop_constraint("ck_job_source", "collection_jobs", type_="check")
    op.create_check_constraint(
        "ck_job_source",
        "collection_jobs",
        "source IN ('serper', 'google_places', 'gbizinfo', 'url', 'csv')",
    )
    op.drop_constraint("ck_search_schedule_source", "search_schedules", type_="check")
    op.create_check_constraint(
        "ck_search_schedule_source",
        "search_schedules",
        "source IN ('serper', 'google_places', 'gbizinfo')",
    )
    op.create_table(
        "ai_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("verdict IN ('correct', 'incorrect')", name="ck_ai_review_verdict"),
    )
    op.create_index("ix_ai_reviews_company_id", "ai_reviews", ["company_id"], unique=True)
    op.create_index("ix_ai_reviews_reviewer_id", "ai_reviews", ["reviewer_id"])
    op.create_table(
        "deals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False, server_default="lead"),
        sa.Column("expected_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_close_date", sa.Date()),
        sa.Column("owner", sa.String(200), nullable=False, server_default=""),
        sa.Column("next_step", sa.Text(), nullable=False, server_default=""),
        sa.Column("lost_reason", sa.String(500), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('lead', 'proposal', 'negotiation', 'won', 'lost')", name="ck_deal_stage"
        ),
        sa.CheckConstraint("expected_amount >= 0", name="ck_deal_expected_amount"),
    )
    op.create_index("ix_deals_company_id", "deals", ["company_id"])
    op.create_index("ix_deals_stage", "deals", ["stage"])
    op.create_table(
        "outreach_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "template_a_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outreach_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "template_b_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outreach_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "template_a_id <> template_b_id", name="ck_experiment_distinct_templates"
        ),
    )
    op.create_index("ix_outreach_experiments_project_id", "outreach_experiments", ["project_id"])
    op.create_index(
        "ix_outreach_experiments_template_a_id", "outreach_experiments", ["template_a_id"]
    )
    op.create_index(
        "ix_outreach_experiments_template_b_id", "outreach_experiments", ["template_b_id"]
    )
    op.add_column(
        "outreach_drafts",
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outreach_experiments.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "outreach_drafts",
        sa.Column("experiment_variant", sa.String(1), nullable=False, server_default=""),
    )
    op.create_index("ix_outreach_drafts_experiment_id", "outreach_drafts", ["experiment_id"])
    op.add_column(
        "outreach_draft_approvals",
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outreach_experiments.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "outreach_draft_approvals",
        sa.Column("experiment_variant", sa.String(1), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_outreach_draft_approvals_experiment_id", "outreach_draft_approvals", ["experiment_id"]
    )


def downgrade():
    op.drop_index(
        "ix_outreach_draft_approvals_experiment_id", table_name="outreach_draft_approvals"
    )
    op.drop_column("outreach_draft_approvals", "experiment_variant")
    op.drop_column("outreach_draft_approvals", "experiment_id")
    op.drop_index("ix_outreach_drafts_experiment_id", table_name="outreach_drafts")
    op.drop_column("outreach_drafts", "experiment_variant")
    op.drop_column("outreach_drafts", "experiment_id")
    op.drop_table("outreach_experiments")
    op.drop_table("deals")
    op.drop_table("ai_reviews")
    op.drop_constraint("ck_search_schedule_source", "search_schedules", type_="check")
    op.create_check_constraint(
        "ck_search_schedule_source", "search_schedules", "source IN ('serper', 'google_places')"
    )
    op.drop_constraint("ck_job_source", "collection_jobs", type_="check")
    op.create_check_constraint(
        "ck_job_source", "collection_jobs", "source IN ('serper', 'google_places', 'url', 'csv')"
    )
    op.drop_constraint("ck_company_source", "companies", type_="check")
    op.create_check_constraint(
        "ck_company_source", "companies", "source IN ('serper', 'google_places', 'url', 'csv')"
    )
