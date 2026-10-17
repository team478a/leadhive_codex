"""Record the source of each form profile analysis."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4f7b2a9c1d30"
down_revision: Union[str, None] = "e2a6c1b8d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_profiles",
        sa.Column("analysis_source", sa.String(length=20), server_default="static", nullable=False),
    )
    op.create_check_constraint(
        "ck_form_profile_analysis_source",
        "form_profiles",
        "analysis_source IN ('static', 'browser')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_form_profile_analysis_source", "form_profiles", type_="check")
    op.drop_column("form_profiles", "analysis_source")
