"""add csv import errors"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "47cc28138178"
down_revision = "d603010b3a67"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "collection_jobs",
        sa.Column(
            "import_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("collection_jobs", "import_errors", server_default=None)


def downgrade():
    op.drop_column("collection_jobs", "import_errors")
