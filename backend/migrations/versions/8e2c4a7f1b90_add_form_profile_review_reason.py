"""add form profile review reason

Revision ID: 8e2c4a7f1b90
Revises: 4f7b2c9d1a60
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e2c4a7f1b90"
down_revision: str | None = "4f7b2c9d1a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "form_profiles",
        sa.Column("delivery_supported", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "form_profiles",
        sa.Column("review_reason", sa.String(length=500), nullable=False, server_default=""),
    )
    op.execute(
        """
        UPDATE form_profiles
        SET form_status = 'REVIEW_REQUIRED',
            review_reason = '送信互換性を確認するため、フォームを再解析してください。'
        WHERE form_status = 'READY'
        """
    )


def downgrade() -> None:
    op.drop_column("form_profiles", "review_reason")
    op.drop_column("form_profiles", "delivery_supported")
