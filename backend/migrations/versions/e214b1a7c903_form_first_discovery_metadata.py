"""Store mutable form-first processing metadata separately from raw discovery snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e214b1a7c903"
down_revision = "214a6f3c9b20"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("collection_discovery_hits")
    }
    if "form_first_metadata" not in columns:
        op.add_column(
            "collection_discovery_hits",
            sa.Column(
                "form_first_metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )


def downgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("collection_discovery_hits")
    }
    if "form_first_metadata" in columns:
        op.drop_column("collection_discovery_hits", "form_first_metadata")
