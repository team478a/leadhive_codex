"""Keep new adapter contracts non-dispatchable until execution evidence is connected."""

from alembic import op

revision = "fc2e7b9d3104"
down_revision = "fb1d6a8c2093"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "ck_adapter_contract_not_consumed",
        "approval_requests",
        "delivery_method <> 'form_adapter' OR status <> 'CONSUMED'",
    )


def downgrade():
    # Never remove the safety boundary while new-method records remain.
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM approval_requests WHERE delivery_method='form_adapter') THEN
      RAISE EXCEPTION 'Adapter contract evidence exists; downgrade forbidden'
        USING ERRCODE='23514';
    END IF; END $$;""")
    op.drop_constraint("ck_adapter_contract_not_consumed", "approval_requests", type_="check")
