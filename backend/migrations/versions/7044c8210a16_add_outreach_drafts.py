"""add outreach drafts"""

import sqlalchemy as sa
from alembic import op

revision = "7044c8210a16"
down_revision = "216f37c1163b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outreach_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("contact_person_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("ai_provider", sa.String(length=50), nullable=False),
        sa.Column("ai_model", sa.String(length=100), nullable=False),
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
        sa.CheckConstraint("channel IN ('email', 'form', 'sns')", name="ck_outreach_draft_channel"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_person_id"], ["contact_people.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreach_drafts_company_id", "outreach_drafts", ["company_id"])
    op.create_index(
        "ix_outreach_drafts_contact_person_id", "outreach_drafts", ["contact_person_id"]
    )
    op.create_index(
        "ix_outreach_drafts_created_by_user_id", "outreach_drafts", ["created_by_user_id"]
    )


def downgrade():
    op.drop_index("ix_outreach_drafts_created_by_user_id", table_name="outreach_drafts")
    op.drop_index("ix_outreach_drafts_contact_person_id", table_name="outreach_drafts")
    op.drop_index("ix_outreach_drafts_company_id", table_name="outreach_drafts")
    op.drop_table("outreach_drafts")
