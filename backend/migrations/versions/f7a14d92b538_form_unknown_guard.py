"""Quarantine uncertain form submissions without rewriting existing migrations."""

from alembic import op

revision = "f7a14d92b538"
down_revision = "f6e03c81f427"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_form_delivery_status", "form_deliveries", type_="check")
    op.create_check_constraint(
        "ck_form_delivery_status",
        "form_deliveries",
        "status IN ('pending','submitted','failed','unknown')",
    )
    op.drop_constraint("ck_form_batch_item_status", "form_delivery_batch_items", type_="check")
    op.create_check_constraint(
        "ck_form_batch_item_status",
        "form_delivery_batch_items",
        "status IN ('queued','submitted','failed','manual_required','skipped','unknown')",
    )


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM form_deliveries WHERE status='unknown')
          OR EXISTS (SELECT 1 FROM form_delivery_batch_items WHERE status='unknown') THEN
          RAISE EXCEPTION 'unresolved form submissions exist; downgrade forbidden';
        END IF; END; $$""")
    op.drop_constraint("ck_form_delivery_status", "form_deliveries", type_="check")
    op.create_check_constraint(
        "ck_form_delivery_status", "form_deliveries", "status IN ('pending','submitted','failed')"
    )
    op.drop_constraint("ck_form_batch_item_status", "form_delivery_batch_items", type_="check")
    op.create_check_constraint(
        "ck_form_batch_item_status",
        "form_delivery_batch_items",
        "status IN ('queued','submitted','failed','manual_required','skipped')",
    )
