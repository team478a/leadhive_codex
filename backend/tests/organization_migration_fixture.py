import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.dialects import postgresql


def seed():
    engine = create_engine(__import__("os").environ["DATABASE_URL"])
    metadata = MetaData()
    names = ("users", "target_profiles", "projects", "companies", "suppression_entries")
    tables = {name: Table(name, metadata, autoload_with=engine) for name in names}

    def insert_required(table, overrides):
        values = dict(overrides)
        for column in table.columns:
            if (
                column.name in values
                or column.nullable
                or column.default is not None
                or column.server_default is not None
            ):
                continue
            kind = column.type
            if column.primary_key and isinstance(kind, postgresql.UUID):
                values[column.name] = uuid.uuid4()
            elif isinstance(kind, postgresql.UUID):
                raise AssertionError(f"missing required foreign key {table.name}.{column.name}")
            elif isinstance(kind, Boolean):
                values[column.name] = False
            elif isinstance(kind, (Integer, Float, Numeric)):
                values[column.name] = 0
            elif isinstance(kind, DateTime):
                values[column.name] = datetime.now(timezone.utc)
            elif isinstance(kind, Date):
                values[column.name] = date.today()
            elif isinstance(kind, (postgresql.JSONB, postgresql.JSON)):
                list_fields = {
                    "search_keywords",
                    "positive_keywords",
                    "negative_keywords",
                    "exclusion_keywords",
                    "default_regions",
                    "protected_fields",
                    "scraped_urls",
                    "ai_strengths",
                    "ai_concerns",
                }
                values[column.name] = [] if column.name in list_fields else {}
            elif isinstance(kind, Text) or hasattr(kind, "length"):
                values[column.name] = "migration fixture"
            else:
                raise AssertionError(
                    f"unhandled required column {table.name}.{column.name}: {kind}"
                )
        with engine.begin() as connection:
            return connection.execute(
                table.insert().values(**values).returning(table.c.id)
            ).scalar_one()

    user_id = uuid.uuid4()
    insert_required(
        tables["users"],
        {"id": user_id, "email": "org-migration@example.test", "password_hash": "fixture"},
    )
    profile_id = insert_required(
        tables["target_profiles"],
        {
            "user_id": user_id,
            "profile_name": "migration profile",
            "description": "",
            "search_keywords": [],
            "positive_keywords": [],
            "negative_keywords": [],
            "exclusion_keywords": [],
            "scoring_rules": {},
            "ai_instruction": "",
            "default_regions": [],
            "is_system": False,
            "active": True,
        },
    )
    project_id = insert_required(
        tables["projects"],
        {
            "user_id": user_id,
            "project_name": "migration project",
            "target_profile_id": profile_id,
            "sales_objective": "",
            "region": "",
            "status": "active",
        },
    )
    insert_required(
        tables["companies"],
        {
            "project_id": project_id,
            "company_name": "legacy DNC",
            "source": "csv",
            "domain": "www.legacy.example",
            "email": "contact@legacy.example",
            "phone": "0312345678",
            "do_not_contact": True,
            "exclusion_reason": "legacy opt out",
            "record_type": "company",
            "location_key": "",
            "status": "unreviewed",
            "analysis_status": "pending",
            "ai_status": "pending",
            "contact_quality_status": "unknown",
        },
    )
    insert_required(
        tables["suppression_entries"],
        {
            "project_id": project_id,
            "domain": "www.project-stop.example",
            "email": "stop@project-stop.example",
            "phone": "",
            "reason": "legacy project stop",
        },
    )
    engine.dispose()


def assert_migrated():
    from sqlalchemy import text

    from app.database import engine

    with engine.connect() as connection:
        project = connection.execute(
            text("SELECT organization_id FROM projects WHERE project_name = :name"),
            {"name": "migration project"},
        ).one()
        owner_count = connection.execute(
            text("SELECT count(*) FROM organization_members WHERE role = 'owner'")
        ).scalar_one()
        project_member_count = connection.execute(
            text("SELECT count(*) FROM project_members")
        ).scalar_one()
        old_stop_count = connection.execute(
            text(
                "SELECT count(*) FROM suppression_entries "
                "WHERE scope = 'project' AND domain = 'www.project-stop.example'"
            )
        ).scalar_one()
        copied_stop_count = connection.execute(
            text(
                "SELECT count(*) FROM suppression_entries WHERE scope = 'organization' "
                "AND organization_id = :org AND domain = 'project-stop.example' "
                "AND source = 'legacy_project'"
            ),
            {"org": project.organization_id},
        ).scalar_one()
        migrated_company_stop_count = connection.execute(
            text(
                "SELECT count(*) FROM suppression_entries WHERE scope = 'organization' "
                "AND organization_id = :org AND domain = 'legacy.example' "
                "AND source = 'legacy_do_not_contact' AND reason = 'legacy opt out'"
            ),
            {"org": project.organization_id},
        ).scalar_one()
    engine.dispose()
    assert owner_count == 1
    assert project_member_count == 0
    assert old_stop_count == copied_stop_count == migrated_company_stop_count == 1
