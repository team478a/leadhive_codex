"""add administrator-managed application settings"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f4c9d42b786e"
down_revision = "e318a9c4d802"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "application_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_app_url", sa.String(2000), nullable=False, server_default=""),
        sa.Column("openai_model", sa.String(200), nullable=False, server_default=""),
        sa.Column("openai_api_key_ciphertext", sa.Text(), nullable=False, server_default=""),
        sa.Column("serper_api_key_ciphertext", sa.Text(), nullable=False, server_default=""),
        sa.Column("google_places_api_key_ciphertext", sa.Text(), nullable=False, server_default=""),
        sa.Column("gbizinfo_api_token_ciphertext", sa.Text(), nullable=False, server_default=""),
        sa.Column("gbizinfo_api_base_url", sa.String(2000), nullable=False, server_default=""),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_settings_updated_by_user_id", "application_settings", ["updated_by_user_id"]
    )


def downgrade():
    op.drop_index("ix_application_settings_updated_by_user_id", table_name="application_settings")
    op.drop_table("application_settings")
