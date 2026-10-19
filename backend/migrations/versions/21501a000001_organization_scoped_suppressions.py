"""Add organizations and organization/global contact suppressions."""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "21501a000001"
down_revision = "e214b1a7c903"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    current_tables = set(inspector.get_table_names())
    if {
        "organizations",
        "organization_members",
        "organization_audit_events",
        "global_opt_out_verifications",
    }.issubset(current_tables):
        project_columns = {column["name"] for column in inspector.get_columns("projects")}
        suppression_columns = {
            column["name"] for column in inspector.get_columns("suppression_entries")
        }
        if "organization_id" in project_columns and {
            "organization_id",
            "scope",
            "source",
            "released_at",
            "released_by_user_id",
            "release_reason",
        }.issubset(suppression_columns):
            audit_trigger_exists = (
                op.get_bind()
                .execute(
                    sa.text(
                        "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                        "WHERE tgname = 'organization_audit_events_append_only' "
                        "AND NOT tgisinternal)"
                    )
                )
                .scalar_one()
            )
            if audit_trigger_exists:
                return

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_organization_status"),
    )
    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('owner', 'admin')", name="ck_organization_member_role"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_member"),
    )
    op.create_index(
        "ix_organization_members_organization_id", "organization_members", ["organization_id"]
    )
    op.create_index("ix_organization_members_user_id", "organization_members", ["user_id"])

    op.add_column("projects", sa.Column("organization_id", postgresql.UUID(as_uuid=True)))
    connection = op.get_bind()
    owner_rows = connection.execute(
        sa.text(
            "SELECT DISTINCT p.user_id, u.email FROM projects p "
            "JOIN users u ON u.id = p.user_id ORDER BY p.user_id"
        )
    ).all()
    owner_organizations = {}
    for user_id, email in owner_rows:
        organization_id = uuid.uuid4()
        owner_organizations[user_id] = organization_id
        connection.execute(
            sa.text("INSERT INTO organizations (id, name, status) VALUES (:id, :name, 'active')"),
            {"id": organization_id, "name": f"利用企業 - {email[:180]}"},
        )
        connection.execute(
            sa.text(
                "INSERT INTO organization_members (id, organization_id, user_id, role) "
                "VALUES (:id, :organization_id, :user_id, 'owner')"
            ),
            {"id": uuid.uuid4(), "organization_id": organization_id, "user_id": user_id},
        )
        connection.execute(
            sa.text(
                "UPDATE projects SET organization_id = :organization_id WHERE user_id = :user_id"
            ),
            {"organization_id": organization_id, "user_id": user_id},
        )
    op.alter_column("projects", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_projects_organization_id_organizations",
        "projects",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])

    op.add_column(
        "suppression_entries",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "suppression_entries",
        sa.Column("scope", sa.String(20), nullable=False, server_default="project"),
    )
    op.add_column(
        "suppression_entries",
        sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
    )
    op.add_column(
        "suppression_entries",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "suppression_entries",
        sa.Column("released_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "suppression_entries",
        sa.Column("released_by_user_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "suppression_entries",
        sa.Column("release_reason", sa.String(500), nullable=False, server_default=""),
    )
    op.alter_column("suppression_entries", "project_id", nullable=True)
    op.execute("UPDATE suppression_entries SET source = 'legacy'")
    op.alter_column("suppression_entries", "scope", server_default="organization")
    op.create_foreign_key(
        "fk_suppression_entries_organization_id_organizations",
        "suppression_entries",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_suppression_entries_created_by_user_id_users",
        "suppression_entries",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_suppression_entries_released_by_user_id_users",
        "suppression_entries",
        "users",
        ["released_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_suppression_entries_created_by_user_id",
        "suppression_entries",
        ["created_by_user_id"],
    )
    op.create_check_constraint(
        "ck_suppression_entry_scope",
        "suppression_entries",
        "(scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL) OR "
        "(scope = 'organization' AND project_id IS NULL AND organization_id IS NOT NULL) OR "
        "(scope = 'global' AND project_id IS NULL AND organization_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_suppression_entry_source",
        "suppression_entries",
        "source IN ('manual', 'legacy', 'legacy_project', 'legacy_do_not_contact', "
        "'email_unsubscribe', 'reply_unsubscribe', 'complaint', 'bounce', 'global_opt_out', "
        "'operator')",
    )
    op.create_index(
        "ix_suppression_entries_org_active",
        "suppression_entries",
        ["organization_id", "released_at"],
    )
    op.create_index(
        "ix_suppression_entries_scope_active",
        "suppression_entries",
        ["scope", "released_at"],
    )

    connection.execute(
        sa.text(
            "INSERT INTO suppression_entries "
            "(id, project_id, organization_id, scope, source, domain, email, phone, reason) "
            "SELECT gen_random_uuid(), NULL, p.organization_id, 'organization', 'legacy_project', "
            "CASE WHEN lower(trim(s.domain)) LIKE 'www.%' "
            "THEN substring(lower(trim(s.domain)) from 5) ELSE lower(trim(s.domain)) END, "
            "lower(trim(s.email)), trim(s.phone), s.reason "
            "FROM suppression_entries s JOIN projects p ON p.id = s.project_id"
        )
    )
    dnc_rows = connection.execute(
        sa.text(
            "SELECT c.domain, c.email, c.phone, c.exclusion_reason, p.organization_id "
            "FROM companies c JOIN projects p ON p.id = c.project_id "
            "WHERE c.do_not_contact IS TRUE"
        )
    ).all()
    for domain, email, phone, reason, organization_id in dnc_rows:
        connection.execute(
            sa.text(
                "INSERT INTO suppression_entries "
                "(id, organization_id, scope, source, domain, email, phone, reason) "
                "VALUES (:id, :organization_id, 'organization', 'legacy_do_not_contact', "
                ":domain, :email, :phone, :reason)"
            ),
            {
                "id": uuid.uuid4(),
                "organization_id": organization_id,
                "domain": (domain or "").strip().lower().removeprefix("www."),
                "email": (email or "").strip().lower(),
                "phone": (phone or "").strip(),
                "reason": (reason or "").strip() or "既存の連絡禁止設定から移行",
            },
        )
    unmatched_dnc_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM companies c JOIN projects p ON p.id = c.project_id "
            "WHERE c.do_not_contact IS TRUE AND NOT EXISTS ("
            "SELECT 1 FROM suppression_entries s WHERE s.scope = 'organization' "
            "AND s.organization_id = p.organization_id AND s.source = 'legacy_do_not_contact' "
            "AND s.domain = CASE WHEN lower(trim(coalesce(c.domain, ''))) LIKE 'www.%' "
            "THEN substring(lower(trim(coalesce(c.domain, ''))) from 5) "
            "ELSE lower(trim(coalesce(c.domain, ''))) END "
            "AND s.email = lower(trim(coalesce(c.email, ''))) "
            "AND s.phone = trim(coalesce(c.phone, '')))"
        )
    ).scalar_one()
    if unmatched_dnc_count:
        raise RuntimeError(
            "Organization suppression migration missed "
            f"{unmatched_dnc_count} do-not-contact companies."
        )

    op.create_table(
        "organization_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "suppression_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("suppression_entries.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_organization_audit_events_organization_id",
        "organization_audit_events",
        ["organization_id"],
    )
    op.create_index(
        "ix_organization_audit_events_suppression_entry_id",
        "organization_audit_events",
        ["suppression_entry_id"],
    )
    op.create_index(
        "ix_organization_audit_events_actor_user_id", "organization_audit_events", ["actor_user_id"]
    )

    op.create_table(
        "global_opt_out_verifications",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("target", sa.String(320), nullable=False),
        sa.Column("verification_email", sa.String(320), nullable=False),
        sa.Column("requester_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_global_opt_out_verifications_target", "global_opt_out_verifications", ["target"]
    )
    op.create_index(
        "ix_global_opt_out_target_created", "global_opt_out_verifications", ["target", "created_at"]
    )
    op.create_index(
        "ix_global_opt_out_requester_created",
        "global_opt_out_verifications",
        ["requester_ip", "created_at"],
    )
    op.create_index(
        "ix_global_opt_out_verifications_expires_at", "global_opt_out_verifications", ["expires_at"]
    )

    op.execute(
        """
        CREATE FUNCTION reject_organization_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'organization audit events are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER organization_audit_events_append_only
        BEFORE UPDATE OR DELETE ON organization_audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_organization_audit_mutation();
        """
    )


def downgrade():
    connection = op.get_bind()
    non_project_count = connection.execute(
        sa.text("SELECT count(*) FROM suppression_entries WHERE scope <> 'project'")
    ).scalar_one()
    if non_project_count:
        raise RuntimeError(
            "Cannot downgrade organization suppressions after organization/global entries exist."
        )
    op.execute("DROP TRIGGER organization_audit_events_append_only ON organization_audit_events")
    op.execute("DROP FUNCTION reject_organization_audit_mutation()")
    op.drop_table("global_opt_out_verifications")
    op.drop_table("organization_audit_events")
    op.drop_index("ix_suppression_entries_scope_active", table_name="suppression_entries")
    op.drop_index("ix_suppression_entries_org_active", table_name="suppression_entries")
    op.drop_constraint("ck_suppression_entry_source", "suppression_entries", type_="check")
    op.drop_constraint("ck_suppression_entry_scope", "suppression_entries", type_="check")
    op.drop_index("ix_suppression_entries_created_by_user_id", table_name="suppression_entries")
    op.drop_constraint(
        "fk_suppression_entries_released_by_user_id_users",
        "suppression_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_suppression_entries_created_by_user_id_users", "suppression_entries", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_suppression_entries_organization_id_organizations",
        "suppression_entries",
        type_="foreignkey",
    )
    op.drop_column("suppression_entries", "release_reason")
    op.drop_column("suppression_entries", "released_by_user_id")
    op.drop_column("suppression_entries", "released_at")
    op.drop_column("suppression_entries", "created_by_user_id")
    op.drop_column("suppression_entries", "source")
    op.drop_column("suppression_entries", "scope")
    op.drop_column("suppression_entries", "organization_id")
    op.alter_column("suppression_entries", "project_id", nullable=False)
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_constraint("fk_projects_organization_id_organizations", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")
    op.drop_table("organization_members")
    op.drop_table("organizations")
