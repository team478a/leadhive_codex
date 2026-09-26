"""add smtp settings"""

import sqlalchemy as sa
from alembic import op

revision = "5d81b9a27ce4"
down_revision = "71b3d5e4a8c2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.execute(
        "UPDATE users SET is_admin = true "
        "WHERE id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)"
    )
    op.alter_column("users", "is_admin", server_default=None)
    op.create_table(
        "smtp_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("password_ciphertext", sa.Text(), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("from_name", sa.String(length=200), nullable=False),
        sa.Column("use_starttls", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
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
    op.create_index("ix_smtp_settings_updated_by_user_id", "smtp_settings", ["updated_by_user_id"])


def downgrade():
    op.drop_index("ix_smtp_settings_updated_by_user_id", table_name="smtp_settings")
    op.drop_table("smtp_settings")
    op.drop_column("users", "is_admin")
