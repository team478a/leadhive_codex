"""Add immutable hostname links and a configurable site interval."""

from urllib.parse import urlsplit

import sqlalchemy as sa
from alembic import op

revision = "fae47ac5e861"
down_revision = "f9c36fb4d750"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "form_dispatch_limits",
        sa.Column("site_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
    )
    op.alter_column("form_dispatch_limits", "site_interval_seconds", server_default=None)
    op.create_check_constraint(
        "ck_form_site_interval",
        "form_dispatch_limits",
        "site_interval_seconds BETWEEN 60 AND 86400",
    )
    links = op.create_table(
        "form_dispatch_sites",
        sa.Column(
            "dispatch_id", sa.Uuid(), sa.ForeignKey("approved_form_dispatches.id"), primary_key=True
        ),
        sa.Column("site_key", sa.String(253), primary_key=True),
    )
    op.create_index("ix_form_dispatch_sites_site_key", "form_dispatch_sites", ["site_key"])
    rows = op.get_bind().execute(
        sa.text(
            "SELECT id, form_url, payload_snapshot->>'form_action_url' AS action_url "
            "FROM approved_form_dispatches"
        )
    )
    for row in rows:
        keys = set()
        for url in (row.form_url, row.action_url):
            parsed = urlsplit(url or "")
            host = (parsed.hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
            if host.startswith("www."):
                host = host[4:]
            if parsed.scheme not in {"http", "https"} or not host or len(host) > 253:
                raise RuntimeError("Existing form reservation has invalid site identity")
            keys.add(host)
        op.bulk_insert(links, [{"dispatch_id": row.id, "site_key": key} for key in keys])
    op.execute("""CREATE FUNCTION immutable_form_site() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Immutable form site evidence' USING ERRCODE='23514'; END $$;
    CREATE TRIGGER form_site_guard BEFORE UPDATE OR DELETE ON form_dispatch_sites
    FOR EACH ROW EXECUTE FUNCTION immutable_form_site();""")


def downgrade():
    op.execute(
        "DROP TRIGGER form_site_guard ON form_dispatch_sites; DROP FUNCTION immutable_form_site();"
    )
    op.drop_table("form_dispatch_sites")
    op.drop_constraint("ck_form_site_interval", "form_dispatch_limits", type_="check")
    op.drop_column("form_dispatch_limits", "site_interval_seconds")
