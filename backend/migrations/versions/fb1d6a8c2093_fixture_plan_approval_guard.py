"""Forbid consumption of non-executable fixture approvals."""

from alembic import op

revision = "fb1d6a8c2093"
down_revision = "fae47ac5e861"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_fixture_plan_not_consumed",
        "approval_requests",
        "delivery_method <> 'form_plan_fixture' OR status <> 'CONSUMED'",
    )


def downgrade():
    op.drop_constraint("ck_fixture_plan_not_consumed", "approval_requests", type_="check")
