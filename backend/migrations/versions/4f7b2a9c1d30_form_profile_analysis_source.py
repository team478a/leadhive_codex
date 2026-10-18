"""Record the source of each form profile analysis."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "4f7b2a9c1d30"
down_revision: Union[str, None] = "e2a6c1b8d904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    column_names = {column["name"] for column in inspector.get_columns("form_profiles")}
    if "analysis_source" not in column_names:
        op.add_column(
            "form_profiles",
            sa.Column(
                "analysis_source",
                sa.String(length=20),
                server_default="static",
                nullable=False,
            ),
        )
    constraint_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("form_profiles")
    }
    if "ck_form_profile_analysis_source" not in constraint_names:
        op.create_check_constraint(
            "ck_form_profile_analysis_source",
            "form_profiles",
            "analysis_source IN ('static', 'browser')",
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    constraint_names = {
        constraint["name"] for constraint in inspector.get_check_constraints("form_profiles")
    }
    if "ck_form_profile_analysis_source" in constraint_names:
        op.drop_constraint("ck_form_profile_analysis_source", "form_profiles", type_="check")
    column_names = {column["name"] for column in inspector.get_columns("form_profiles")}
    if "analysis_source" in column_names:
        op.drop_column("form_profiles", "analysis_source")
