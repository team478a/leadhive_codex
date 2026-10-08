"""add outreach conversion attribution"""

import sqlalchemy as sa
from alembic import op

revision = "3f47c2ad8b9e"
down_revision = "8c7a1607623b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "inbound_emails",
        sa.Column("outreach_approval_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_inbound_emails_outreach_approval_id",
        "inbound_emails",
        "outreach_draft_approvals",
        ["outreach_approval_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_inbound_emails_outreach_approval_id",
        "inbound_emails",
        ["outreach_approval_id"],
    )
    op.create_table(
        "outreach_conversions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_email_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('replied', 'meeting', 'won')",
            name="ck_outreach_conversion_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["outreach_draft_approvals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inbound_email_id"], ["inbound_emails.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_conversions_approval_id", "outreach_conversions", ["approval_id"])
    op.create_index("ix_outreach_conversions_company_id", "outreach_conversions", ["company_id"])
    op.create_index(
        "ix_outreach_conversions_inbound_email_id", "outreach_conversions", ["inbound_email_id"]
    )
    op.create_index("ix_outreach_conversions_occurred_at", "outreach_conversions", ["occurred_at"])


def downgrade():
    op.drop_index("ix_outreach_conversions_occurred_at", table_name="outreach_conversions")
    op.drop_index("ix_outreach_conversions_inbound_email_id", table_name="outreach_conversions")
    op.drop_index("ix_outreach_conversions_company_id", table_name="outreach_conversions")
    op.drop_index("ix_outreach_conversions_approval_id", table_name="outreach_conversions")
    op.drop_table("outreach_conversions")
    op.drop_index("ix_inbound_emails_outreach_approval_id", table_name="inbound_emails")
    op.drop_constraint(
        "fk_inbound_emails_outreach_approval_id", "inbound_emails", type_="foreignkey"
    )
    op.drop_column("inbound_emails", "outreach_approval_id")
