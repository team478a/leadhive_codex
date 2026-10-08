"""Freeze the legacy cohort through READ ONLY, measure an isolated projection.

No source credentials, sessions, contact people, website text or freeform notes are
exported. Business location/contact fields stay in an ignored local snapshot.
Public output is exclusively aggregate data. No worker or external client runs.
"""

import argparse
import copy
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.services.benchmark_summary import costs, summarize
from app.services.cohort_destinations import page
from app.services.completion_metrics import cohort_digest
from app.services.form_intelligence.fields import mapping_review_reason
from app.services.sales_preparation import context_hash

COMPANY_FIELDS = {
    "id",
    "project_id",
    "record_type",
    "location_key",
    "company_name",
    "address",
    "phone",
    "website_url",
    "reference_url",
    "domain",
    "contact_url",
    "email",
    "source",
    "source_keyword",
    "prefecture",
    "city",
    "do_not_contact",
    "protected_fields",
    "contact_quality_status",
    "contact_checked_at",
    "contact_source_url",
    "analysis_status",
    "ai_status",
    "score",
    "rank",
    "is_target",
    "ai_analyzed_at",
    "created_at",
    "updated_at",
}
MODERN = [
    "lead_source_observations",
    "lead_site_evidence",
    "contact_destinations",
    "lead_destination_links",
    "site_identity_review_events",
    "destination_review_events",
    "destination_choice_events",
    "lead_dm_preparations",
    "lead_processing_usage",
    "lead_review_sessions",
    "lead_completion_cohorts",
]


def redact_capture(captured, cohort_hash):
    """Keep predicates, omit freeform DOM/value/log text and human identifiers."""
    excluded = {
        "form_profiles": {"review_reason", "error_message"},
        "form_profile_fields": {
            "recommended_value",
            "surrounding_text",
            "placeholder",
            "aria_label",
            "label",
            "options",
        },
        "suppression_entries": {"reason"},
    }
    for name, fields in excluded.items():
        for row in captured[name]:
            for field in fields:
                row.pop(field, None)
            if name == "suppression_entries":
                row["reason"] = "Stored suppression retained; freeform reason omitted"
    for name in ("projects", "target_profiles"):
        for row in captured[name]:
            if row.get("user_id"):
                row["user_id"] = uuid.uuid5(uuid.NAMESPACE_URL, f"benchmark-owner:{cohort_hash}")
    return captured


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--members", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source_url = make_url(os.environ["BENCHMARK_SOURCE_DATABASE_URL"])
    target_url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (target_url.database or "").endswith("_test") or target_url == source_url:
        raise RuntimeError("An isolated _test projection is required")
    if settings.outbound_enabled or settings.agent_features_enabled:
        raise RuntimeError("Outbound and Agent flags must stay OFF")
    root = Path(__file__).resolve().parents[2]
    private = Path(args.snapshot).resolve()
    if not private.is_relative_to(root / "dist") or private.exists():
        raise RuntimeError("New private snapshot must be inside ignored dist")
    manifest = json.loads(Path(args.members).read_text(encoding="utf-8-sig"))
    ids = sorted({uuid.UUID(r["company_id"]) for r in manifest["private_details"]})
    if len(ids) != 100:
        raise RuntimeError("Exactly the original 100 fixed members are required")
    project_id = uuid.UUID(args.project_id)
    source = create_engine(source_url)
    captured = {}
    with source.connect() as connection:
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        names = set(inspect(connection).get_table_names())
        migration = connection.scalar(text("SELECT version_num FROM alembic_version"))
        # This compatibility runner deliberately cannot silently omit populated new ledgers.
        if any(name in names for name in MODERN):
            raise RuntimeError("Use current-schema read-only measurement, not legacy projection")
        meta = MetaData()

        def table(name):
            return Table(name, meta, autoload_with=connection)

        companies = table("companies")
        captured["companies"] = [
            dict(r)
            for r in connection.execute(
                select(*(c for c in companies.c if c.name in COMPANY_FIELDS)).where(
                    companies.c.project_id == project_id,
                    companies.c.id.in_(ids),
                )
            ).mappings()
        ]
        projects = table("projects")
        captured["projects"] = [
            dict(
                connection.execute(select(projects).where(projects.c.id == project_id))
                .mappings()
                .one()
            )
        ]
        profile_id = captured["projects"][0]["target_profile_id"]
        profiles = table("target_profiles")
        captured["target_profiles"] = [
            dict(
                connection.execute(select(profiles).where(profiles.c.id == profile_id))
                .mappings()
                .one()
            )
        ]
        for name in ["email_deliveries", "form_deliveries", "contact_people", "approval_requests"]:
            if name not in names:
                continue
            item = table(name)
            column = item.c.project_id if "project_id" in item.c else item.c.company_id
            scope = column == project_id if column.name == "project_id" else column.in_(ids)
            if connection.scalar(select(func.count()).select_from(item).where(scope)):
                raise RuntimeError("Projection would omit personal contacts or execution evidence")
        form = table("form_profiles")
        captured["form_profiles"] = [
            dict(r)
            for r in connection.execute(select(form).where(form.c.company_id.in_(ids))).mappings()
        ]
        fields = table("form_profile_fields")
        captured["form_profile_fields"] = [
            dict(r)
            for r in connection.execute(
                select(fields).where(
                    fields.c.form_profile_id.in_([r["id"] for r in captured["form_profiles"]])
                )
            ).mappings()
        ]
        suppression = table("suppression_entries")
        captured["suppression_entries"] = [
            dict(r)
            for r in connection.execute(
                select(suppression).where(suppression.c.project_id == project_id)
            ).mappings()
        ]
        captured_at = datetime.now(timezone.utc)
        connection.rollback()
    source.dispose()
    # Keep original mapping predicates in the transient projection. Freeform DOM
    # values are not exported, and redaction must not alter the measured decision.
    safe_capture = redact_capture(copy.deepcopy(captured), cohort_digest([str(i) for i in ids]))
    mapping_predicates = [
        dict(
            form_profile_id=str(p["id"]),
            required_field_unknown=bool(
                mapping_review_reason(
                    [f for f in captured["form_profile_fields"] if f["form_profile_id"] == p["id"]]
                )
            ),
        )
        for p in captured["form_profiles"]
    ]
    for name in ("projects", "target_profiles"):
        for raw_row, safe_row in zip(captured[name], safe_capture[name], strict=True):
            raw_row["user_id"] = safe_row["user_id"]
    snapshot = dict(
        source_migration=migration,
        captured_at=captured_at.isoformat(),
        company_ids=[str(i) for i in ids],
        cohort_hash=cohort_digest([str(i) for i in ids]),
        missing_schema=MODERN,
        tables=safe_capture,
        form_mapping_predicates=mapping_predicates,
        privacy="LOCAL_IGNORED_BUSINESS_RECORDS_ONLY; no user/session/credential/person data",
        excluded_fields=[
            "website_text",
            "notes",
            "assignee",
            "ai_summary",
            "ai_reason",
            "form_recommended_value",
            "form_freeform_text",
            "suppression_freeform_reason",
            "human_user_identity",
        ],
        source_ai_context_binding="NOT_RECORDED_IN_LEGACY_SCHEMA_NOT_INFERRED",
    )
    raw = json.dumps(snapshot, default=str, ensure_ascii=False, sort_keys=True, indent=2)
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(raw, encoding="utf-8", newline="\n")
    source_hash = hashlib.sha256(raw.encode()).hexdigest()
    target = create_engine(target_url)
    with Session(target) as db:
        if db.scalar(select(func.count()).select_from(models.Company)):
            raise RuntimeError("Projection target must be empty")
        owner_ids = {
            captured["projects"][0]["user_id"],
            captured["target_profiles"][0].get("user_id"),
        }
        owner_ids |= {r.get("created_by_user_id") for r in captured["suppression_entries"]}
        for user_id in owner_ids - {None}:
            db.add(
                models.User(
                    id=user_id,
                    email=f"benchmark-{user_id}@example.invalid",
                    password_hash="!disabled-benchmark",
                )
            )
        db.flush()
        for name in [
            "target_profiles",
            "projects",
            "companies",
            "form_profiles",
            "form_profile_fields",
            "suppression_entries",
        ]:
            model = next(
                m
                for m in [
                    models.TargetProfile,
                    models.Project,
                    models.Company,
                    models.FormProfile,
                    models.FormProfileField,
                    models.SuppressionEntry,
                ]
                if m.__tablename__ == name
            )
            columns = {c.name for c in model.__table__.columns}
            for row in captured[name]:
                db.add(model(**{k: v for k, v in row.items() if k in columns}))
            db.flush()
        project = db.get(models.Project, project_id)
        profile = db.get(models.TargetProfile, profile_id)
        assert project is not None and profile is not None
        cohort = models.LeadCompletionCohort(
            project_id=project_id,
            created_by_user_id=project.user_id,
            name="Fixed stored-data benchmark",
            company_ids=[str(i) for i in ids],
            cohort_hash=snapshot["cohort_hash"],
            context_hash=context_hash(project, profile),
            created_at=captured_at,
        )
        db.add(cohort)
        db.commit()
        cohort_id = cohort.id
    with Session(target) as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        loaded_cohort = db.get(models.LeadCompletionCohort, cohort_id)
        assert loaded_cohort is not None
        cohort = loaded_cohort
        project = db.get(models.Project, project_id)
        assert project is not None
        rows = []
        for offset in range(0, 100, 25):
            rows.extend(page(db, cohort, project, offset, 25, benchmark=True)["rows"])
        result = summarize(rows, 100, dict(cost=costs(db, cohort, project)))
        result.update(
            cohort_hash=snapshot["cohort_hash"],
            snapshot_sha256=source_hash,
            snapshot_hash_encoding="UTF8_NORMALIZED_LF",
            snapshot_file_sha256=hashlib.sha256(private.read_bytes()).hexdigest(),
            input_commit="13a1d071d0f9d9c1d28b7d7a1f32f15245081c01",
            requested_baseline="a0233d1a9a1a5b321c1e08f89e21ae021070db3f",
            source_migration=migration,
            measured_at=datetime.now(timezone.utc).isoformat(),
            schema_projection_missing=MODERN,
            privacy="AGGREGATES_ONLY",
            baseline=json.loads(
                (root / "docs/results/lead-completion-baseline-2026-10-06.json").read_text()
            ),
            benchmark_execution=dict(
                search_calls=0,
                places_calls=0,
                ai_calls=0,
                email_sent=0,
                form_sent=0,
                approvals=0,
                outbound=False,
                worker_started=False,
                external_get=0,
            ),
        )
        measured = dict(
            company_ids=snapshot["company_ids"],
            measurements=[
                dict(
                    company_id=str(r["company_id"]),
                    benchmark=r["benchmark"],
                    dm_ready=r["dm_ready"],
                    delivery_funnel=r["delivery_funnel"],
                )
                for r in rows
            ],
        )
        private.with_name(private.stem + "-measurements.json").write_text(
            json.dumps(measured, default=str, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        db.rollback()
    target.dispose()
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "discovered": result["discovered"],
                "sendability": result["sendability"],
                "dm_ready": result["dm_ready"],
                "snapshot_sha256": source_hash,
            }
        )
    )


if __name__ == "__main__":
    main()
