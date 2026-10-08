"""track outreach delivery completion"""

import sqlalchemy as sa
from alembic import op

revision = "6d28a1ce4f7b"
down_revision = "3f47c2ad8b9e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outreach_draft_approvals",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outreach_draft_approvals_delivered_at",
        "outreach_draft_approvals",
        ["delivered_at"],
    )
    op.execute(
        """
        UPDATE outreach_draft_approvals AS approval
        SET delivered_at = delivery.sent_at
        FROM email_deliveries AS delivery
        WHERE approval.draft_id = delivery.draft_id
          AND approval.approval_type = 'email'
          AND delivery.status = 'sent'
          AND delivery.sent_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE outreach_draft_approvals AS approval
        SET delivered_at = delivery.submitted_at
        FROM form_deliveries AS delivery
        WHERE approval.draft_id = delivery.draft_id
          AND delivery.status = 'submitted'
          AND delivery.submitted_at IS NOT NULL
          AND (
            (approval.approval_type = 'form_direct' AND delivery.delivery_method = 'direct')
            OR (
                approval.approval_type = 'form_codex'
                AND delivery.delivery_method = 'codex_assisted'
            )
          )
        """
    )


def downgrade():
    op.drop_index("ix_outreach_draft_approvals_delivered_at", table_name="outreach_draft_approvals")
    op.drop_column("outreach_draft_approvals", "delivered_at")
