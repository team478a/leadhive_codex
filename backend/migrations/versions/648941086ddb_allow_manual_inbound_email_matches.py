"""allow manual inbound email matches"""

from alembic import op

revision = "648941086ddb"
down_revision = "e6ab1a60add4"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_inbound_email_match_type", "inbound_emails", type_="check")
    op.create_check_constraint(
        "ck_inbound_email_match_type",
        "inbound_emails",
        "match_type IN ('company_email', 'contact_person', 'manual', 'unmatched')",
    )


def downgrade():
    op.execute("UPDATE inbound_emails SET match_type = 'unmatched' WHERE match_type = 'manual'")
    op.drop_constraint("ck_inbound_email_match_type", "inbound_emails", type_="check")
    op.create_check_constraint(
        "ck_inbound_email_match_type",
        "inbound_emails",
        "match_type IN ('company_email', 'contact_person', 'unmatched')",
    )
