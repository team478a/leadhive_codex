"""track scraped pages"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "69fca6fd2dab"
down_revision = "3f2dd0cd2e4b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "companies",
        sa.Column(
            "scraped_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.alter_column("companies", "scraped_urls", server_default=None)


def downgrade():
    op.drop_column("companies", "scraped_urls")
