"""Seed immutable system target profiles; industry differences are JSON data."""

import json
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c04b62783e12"
down_revision = "fbff25327336"
branch_labels = None
depends_on = None


def profile_table():
    return sa.table(
        "target_profiles",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("profile_name", sa.String()),
        sa.column("description", sa.Text()),
        *(
            sa.column(name, JSONB())
            for name in (
                "search_keywords",
                "positive_keywords",
                "negative_keywords",
                "exclusion_keywords",
                "scoring_rules",
                "default_regions",
            )
        ),
        sa.column("ai_instruction", sa.Text()),
        sa.column("is_system", sa.Boolean()),
        sa.column("active", sa.Boolean()),
    )


def seed_data():
    path = Path(__file__).parent.parent / "data" / "0002_system_profiles.json"
    profiles = json.loads(path.read_text(encoding="utf-8"))
    for profile in profiles:
        profile["id"] = UUID(profile["id"])
    return profiles


def upgrade():
    op.bulk_insert(profile_table(), seed_data())


def downgrade():
    table = profile_table()
    # Referenced seeds are protected by the project FK; never silently remove project data.
    op.execute(table.delete().where(table.c.id.in_([p["id"] for p in seed_data()])))
