"""connect form intelligence to approved delivery

Revision ID: 6a1d9e4c2b70
Revises: 2f6c8a9b1d4e
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6a1d9e4c2b70"
down_revision: str | None = "2f6c8a9b1d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "form_sender_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("department", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("position", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("contact_name", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("first_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("furigana", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("postal_code", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("prefecture", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("city", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("address", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("building", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("website", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_form_sender_settings_updated_by_user_id",
        "form_sender_settings",
        ["updated_by_user_id"],
    )
    op.add_column("form_deliveries", sa.Column("form_profile_id", sa.Uuid(), nullable=True))
    op.add_column(
        "form_deliveries",
        sa.Column("profile_fingerprint", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "form_deliveries",
        sa.Column(
            "field_mapping_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_form_deliveries_form_profile_id",
        "form_deliveries",
        "form_profiles",
        ["form_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_form_deliveries_form_profile_id", "form_deliveries", ["form_profile_id"])


def downgrade() -> None:
    op.drop_index("ix_form_deliveries_form_profile_id", table_name="form_deliveries")
    op.drop_constraint(
        "fk_form_deliveries_form_profile_id", "form_deliveries", type_="foreignkey"
    )
    op.drop_column("form_deliveries", "field_mapping_snapshot")
    op.drop_column("form_deliveries", "profile_fingerprint")
    op.drop_column("form_deliveries", "form_profile_id")
    op.drop_index("ix_form_sender_settings_updated_by_user_id", table_name="form_sender_settings")
    op.drop_table("form_sender_settings")
