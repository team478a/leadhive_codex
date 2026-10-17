"""add split sender identity fields

Revision ID: a71c4f09d2e6
Revises: f14c9b7a6d20
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a71c4f09d2e6"
down_revision: str | None = "f14c9b7a6d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "form_sender_settings",
        sa.Column("last_name_furigana", sa.String(length=200), server_default="", nullable=False),
    )
    op.add_column(
        "form_sender_settings",
        sa.Column("first_name_furigana", sa.String(length=200), server_default="", nullable=False),
    )
    op.add_column(
        "form_sender_settings",
        sa.Column("phone_area_code", sa.String(length=20), server_default="", nullable=False),
    )
    op.add_column(
        "form_sender_settings",
        sa.Column("phone_exchange_code", sa.String(length=20), server_default="", nullable=False),
    )
    op.add_column(
        "form_sender_settings",
        sa.Column("phone_line_number", sa.String(length=20), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("form_sender_settings", "phone_line_number")
    op.drop_column("form_sender_settings", "phone_exchange_code")
    op.drop_column("form_sender_settings", "phone_area_code")
    op.drop_column("form_sender_settings", "first_name_furigana")
    op.drop_column("form_sender_settings", "last_name_furigana")
